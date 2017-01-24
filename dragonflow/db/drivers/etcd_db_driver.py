#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from socket import timeout as SocketTimeout

from contextlib import contextmanager
import etcd
import eventlet
from oslo_log import log
import urllib3
from urllib3 import connection
from urllib3 import exceptions

from dragonflow._i18n import _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api

LOG = log.getLogger(__name__)

# Monkey patch urllib3 to close connections that time out.  Otherwise,
# etcd will leak socket handles when we time out watches.

ETCD_READ_TIMEOUT = 20


@contextmanager
def _error_catcher(self):
    """
    Catch low-level python exceptions, instead re-raising urllib3
    variants, so that low-level exceptions are not leaked in the
    high-level api.
    On exit, release the connection back to the pool.
    """
    try:
        try:
            yield

        except SocketTimeout:
            # FIXME: Ideally we'd like to include the url in the
            # ReadTimeoutError but there is yet no clean way to
            # get at it from this context.
            raise exceptions.ReadTimeoutError(
                self._pool, None, 'Read timed out.')

        except connection.BaseSSLError as e:
            # FIXME: Is there a better way to differentiate between SSLErrors?
            if 'read operation timed out' not in str(e):  # Defensive:
                # This shouldn't happen but just in case we're missing an edge
                # case, let's avoid swallowing SSL errors.
                raise

            raise exceptions.ReadTimeoutError(
                self._pool, None, 'Read timed out.')

        except connection.HTTPException as e:
            # This includes IncompleteRead.
            raise exceptions.ProtocolError('Connection broken: %r' % e, e)
    except Exception:
        # The response may not be closed but we're not going to use it anymore
        # so close it now to ensure that the connection is released back to the
        #  pool.
        if self._original_response and not self._original_response.isclosed():
            self._original_response.close()

        # Before returning the socket, close it.  From the server's
        # point of view,
        # this socket is in the middle of handling an SSL handshake/HTTP
        # request so it we were to try and re-use the connection later,
        #  we'd see undefined behaviour.
        #
        # Still return the connection to the pool (it will be
        # re-established next time it is used).
        self._connection.close()

        raise
    finally:
        if self._original_response and self._original_response.isclosed():
            self.release_conn()
urllib3.HTTPResponse._error_catcher = _error_catcher


def _check_valid_host(host_str):
    return ':' in host_str and host_str[-1] != ':'


def _parse_hosts(hosts):
    host_ports = []
    for host_str in hosts:
        if _check_valid_host(host_str):
            host_port = host_str.strip().split(':')
            host_ports.append((host_port[0], int(host_port[1])))
        else:
            LOG.error(_LE("The host string %s is invalid."), host_str)
    return tuple(host_ports)


class EtcdDbDriver(db_api.DbApi):

    def __init__(self):
        super(EtcdDbDriver, self).__init__()
        self.client = None
        self.current_key = 0
        self.notify_callback = None
        self.pool = eventlet.GreenPool(size=1)

    def initialize(self, db_ip, db_port, **args):
        hosts = _parse_hosts(args['config'].remote_db_hosts)
        if hosts:
            self.client = etcd.Client(host=hosts, allow_reconnect=True)
        else:
            self.client = etcd.Client(host=db_ip, port=db_port)

    def support_publish_subscribe(self):
        return True

    def create_table(self, table):
        # Not needed in etcd
        pass

    def delete_table(self, table):
        # Not needed in etcd
        pass

    def get_key(self, table, key, topic=None):
        try:
            return self.client.read('/' + table + '/' + key).value
        except etcd.EtcdKeyNotFound:
            raise df_exceptions.DBKeyNotFound(key=key)

    def set_key(self, table, key, value, topic=None):
        self.client.write('/' + table + '/' + key, value)

    def create_key(self, table, key, value, topic=None):
        self.client.write('/' + table + '/' + key, value)

    def delete_key(self, table, key, topic=None):
        try:
            self.client.delete('/' + table + '/' + key)
        except etcd.EtcdKeyNotFound:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        res = []
        try:
            directory = self.client.get("/" + table)
        except etcd.EtcdKeyNotFound:
            return res
        for entry in directory.children:
            if entry.value:
                res.append(entry.value)
        return res

    def get_all_keys(self, table, topic=None):
        res = []
        try:
            directory = self.client.get("/" + table)
        except etcd.EtcdKeyNotFound:
            raise df_exceptions.DBKeyNotFound(key=table)
        for entry in directory.children:
            table_name_size = len(table) + 2
            res.append(entry.key[table_name_size:])
        return res

    def _allocate_unique_key(self, table):
        key = '/unique_key/%s' % table
        prev_value = 0
        try:
            prev_value = int(self.client.read(key).value)
            self.client.test_and_set(key, str(prev_value + 1), str(prev_value))
            return prev_value + 1
        except Exception:
            if prev_value == 0:
                self.client.write(key, "1", prevExist=False)
                return 1
            raise

    def allocate_unique_key(self, table):
        while True:
            try:
                return self._allocate_unique_key(table)
            except Exception:
                pass

    def register_notification_callback(self, callback):
        self.notify_callback = callback
        self.pool.spawn_n(self._db_changes_updater)

    def register_topic_for_notification(self, topic):
        # TODO(gsagie) implement this
        pass

    def unregister_topic_for_notification(self, topic):
        # TODO(gsagie) implement this
        pass

    def process_ha(self):
        # Not needed in etcd
        pass

    def set_neutron_server(self, is_neutron_server):
        # Not needed in etcd
        pass

    def _db_changes_updater(self):
        while True:
            try:
                entry = self.client.read('/', wait=True, recursive=True,
                                         waitIndex=self.current_key,
                                         timeout=ETCD_READ_TIMEOUT)
                keys = entry.key.split('/')
                self.notify_callback(keys[1], keys[2], entry.action,
                                     entry.value, None)
                self.current_key = entry.modifiedIndex + 1
            except Exception as e:
                if "Read timed out" not in e.message:
                    LOG.warning(e)
                    self.notify_callback(None, None, 'sync',
                                         None, None)
