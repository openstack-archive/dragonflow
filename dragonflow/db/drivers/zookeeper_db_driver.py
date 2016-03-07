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

import time

import kazoo
from kazoo.client import KazooClient
from kazoo.handlers.eventlet import SequentialEventletHandler
from kazoo.retry import KazooRetry

from oslo_log import log
from oslo_utils import excutils
from oslo_utils import reflection
import six

from dragonflow._i18n import _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api

LOG = log.getLogger(__name__)

ROOT_NS = '/openstack'

CLIENT_CONNECTION_RETRIES = -1

ZK_MAX_RETRIES = 3


class wrap_zookeeper_retry(object):
    """Retry zookeeper methods, if zk_error raised

    Retry decorated zookeeper methods. This decorator catches zk_error
    and retries function in a loop until it succeeds, or until maximum
    retries count will be reached.

    Keyword arguments:

    :param retry_interval: seconds between operation retries
    :type retry_interval: int

    :param max_retries: max number of retries before an error is raised
    :type max_retries: int

    :param inc_retry_interval: determine increase retry interval or not
    :type inc_retry_interval: bool

    :param max_retry_interval: max interval value between retries
    :type max_retry_interval: int

    :param exception_checker: checks if an exception should trigger a retry
    :type exception_checker: callable
    """

    def __init__(self, retry_interval=0, max_retries=0, inc_retry_interval=0,
                 max_retry_interval=0, exception_checker=lambda exc: False):
        super(wrap_zookeeper_retry, self).__init__()

        self.zk_error = ()
        # default is that we re-raise anything unexpected
        self.exception_checker = exception_checker
        self.zk_error += (kazoo.exceptions.SessionExpiredError, )
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.inc_retry_interval = inc_retry_interval
        self.max_retry_interval = max_retry_interval

    def __call__(self, f):
        @six.wraps(f)
        def wrapper(*args, **kwargs):
            next_interval = self.retry_interval
            remaining = self.max_retries

            while True:
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    with excutils.save_and_reraise_exception() as ectxt:
                        if remaining > 0:
                            ectxt.reraise = not self._is_exception_expected(e)
                        else:
                            LOG.exception(_LE('Zookeeper exceeded '
                                              'retry limit.'))
                    LOG.debug("Performing Zookeeper retry for function %s",
                              reflection.get_callable_name(f))
                    # NOTE(vsergeyev): We are using patched time module, so
                    #                  this effectively yields the execution
                    #                  context to another green thread.
                    time.sleep(next_interval)
                    if self.inc_retry_interval:
                        next_interval = min(
                            next_interval * 2,
                            self.max_retry_interval
                        )
                    remaining -= 1
        return wrapper

    def _is_exception_expected(self, exc):
        if isinstance(exc, self.zk_error):
            return True
        return self.exception_checker(exc)


def _parse_hosts(hosts):
    if isinstance(hosts, six.string_types):
        return hosts.strip()
    if isinstance(hosts, (dict)):
        host_ports = []
        for (k, v) in six.iteritems(hosts):
            host_ports.append("%s:%s" % (k, v))
        hosts = host_ports
    if isinstance(hosts, (list, set, tuple)):
        return ",".join([str(h) for h in hosts])
    return hosts


class ZookeeperDbDriver(db_api.DbApi):

    def __init__(self):
        super(ZookeeperDbDriver, self).__init__()
        self.client = None
        self.db_ip = None
        self.db_port = None
        self.config = None

    def initialize(self, db_ip, db_port, **args):
        self.db_ip = db_ip
        self.db_port = db_port
        self.config = args['config']

    def _lazy_initialize(self):
        if not self.client:
            hosts = _parse_hosts(self.config.remote_db_hosts)
            _handler = SequentialEventletHandler()
            _retry = KazooRetry(max_tries=CLIENT_CONNECTION_RETRIES,
                                delay=0.5,
                                backoff=2,
                                sleep_func=_handler.sleep_func)
            self.client = KazooClient(hosts=hosts,
                                      handler=_handler,
                                      connection_retry=_retry)
            self.client.start()
            self.client.ensure_path(ROOT_NS)

    def support_publish_subscribe(self):
        return False

    def _generate_path(self, table, key):
        if not key:
            return ROOT_NS + '/' + table
        else:
            return ROOT_NS + '/' + table + '/' + key

    def get_key(self, table, key):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            ret = self.client.get(path)[0]
            return ret
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    @wrap_zookeeper_retry(max_retries=ZK_MAX_RETRIES,
                          retry_interval=1,
                          inc_retry_interval=True,
                          max_retry_interval=10)
    def set_key(self, table, key, value):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            self.client.set(path, value)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    @wrap_zookeeper_retry(max_retries=ZK_MAX_RETRIES,
                          retry_interval=1,
                          inc_retry_interval=True,
                          max_retry_interval=10)
    def create_key(self, table, key, value):
        path = self._generate_path(table, key)
        self._lazy_initialize()
        self.client.create(path, value, makepath=True)

    @wrap_zookeeper_retry(max_retries=ZK_MAX_RETRIES,
                          retry_interval=1,
                          inc_retry_interval=True,
                          max_retry_interval=10)
    def delete_key(self, table, key):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            self.client.delete(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        res = []
        path = self._generate_path(table, None)
        try:
            self._lazy_initialize()
            directory = self.client.get_children(path)
            for key in directory:
                res.append(self.get_key(table, key))
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)
        return res

    def get_all_keys(self, table, topic=None):
        path = self._generate_path(table, None)
        try:
            self._lazy_initialize()
            return self.client.get_children(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)

    def _allocate_unique_key(self):
        path = self._generate_path('tunnel_key', 'key')

        prev_value = 0
        version_exception = True
        while version_exception:
            try:
                prev_value, stat = self.client.get(path)
                prev_value = int(prev_value)
                prev_version = stat.version
                self.client.set(path, str(prev_value + 1), prev_version)
                return prev_value + 1
            except kazoo.exceptions.BadVersionError:
                version_exception = True
            except kazoo.exceptions.NoNodeError:
                self.client.create(path, "1", makepath=True)
                return 1

    def allocate_unique_key(self):
        self._lazy_initialize()
        return self._allocate_unique_key()

    def register_notification_callback(self, callback):
        #NOTE(nick-ma-z): The pub-sub mechanism is not initially supported.
        #                 The watcher function of Zookeeper only supports
        #                 one-time trigger. You have to continuously register
        #                 watchers for each children. Moreover, the delay
        #                 between trigger and registration causes lose of
        #                 events. The DataWatch of Kazoo is also not that
        #                 stable and easy to use. Thanks to build-in pub-sub
        #                 of dragonflow, we don't need to work hard on zk side.
        #                 Please set 'enable_df_pub_sub=True' in the
        #                 configuration to enable the build-in pubsub function.
        return

    def register_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass

    def unregister_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass
