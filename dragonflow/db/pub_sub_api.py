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

import abc
import socket
import time
import uuid

import eventlet
import msgpack
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _LE, _LI
from dragonflow.common import exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import models

LOG = logging.getLogger(__name__)

eventlet.monkey_patch(socket=False)

MONITOR_TABLES = [models.Chassis.table_name, models.Publisher.table_name]


def pack_message(message):
    data = None
    try:
        data = msgpack.packb(message, encoding='utf-8')
    except Exception:
        LOG.exception(_LE("Error in pack_message: "))
    return data


def unpack_message(message):
    entry = None
    try:
        entry = msgpack.unpackb(message, encoding='utf-8')
    except Exception:
        LOG.exception(_LE("Error in unpack_message: "))
    return entry


def generate_publisher_uuid():
    """
    Generate a non-random uuid based on the fully qualified domain name.
    This UUID is supposed to remain the same across service restarts.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.getfqdn()))


@six.add_metaclass(abc.ABCMeta)
class PubSubApi(object):
    """
    API class to get the publisher and subscriber in the controller and neutron
    plugin.
    """

    @abc.abstractmethod
    def get_publisher(self):
        """Return a Publisher Driver Object

        :returns: an PublisherApi Object
        """

    @abc.abstractmethod
    def get_subscriber(self):
        """Return a Subscriber Driver Object

        :returns: an PublisherApi Object. My return None if is_local is true,
                  and local and non-local publishers are the same.
        """


@six.add_metaclass(abc.ABCMeta)
class PublisherApi(object):

    @abc.abstractmethod
    def initialize(self):
        """Initialize the DB client

        :param endpoint: ip:port
        :type endpoint: string
        :param trasport_proto: protocol to use tcp:epgm ...
        :type trasport_proto: string
        :param args: Additional args
        :type args:        dictionary of <string, object>
        :returns:          None
        """

    @abc.abstractmethod
    def send_event(self, update, topic):
        """Publish the update

        :param update:  Encapsulates a Publisher update
        :type update:   DbUpdate object
        :param topic:   topic to send event to
        :type topic:    string
        :returns:       None
        """

    @abc.abstractmethod
    def close(self):
        """Close the publisher. Release all used resources"""

    def set_publisher_for_failover(self, pub, callback):
        pass

    def start_detect_for_failover(self):
        pass

    def process_ha(self):
        pass


@six.add_metaclass(abc.ABCMeta)
class SubscriberApi(object):

    @abc.abstractmethod
    def initialize(self, callback):
        """Initialize the DB client

        :param callback:  callback method to call for every db change
        :type callback :  callback method of type:
                          callback(table, key, action, value, topic)
                          table - table name
                          key - object key
                          action = 'create' / 'set' / 'delete' / 'sync'
                          value = new object value
                          topic - the topic with which the event was received
        :param args:       Additional args
        :type args:        dictionary of <string, object>
        :returns:          None
        """

    @abc.abstractmethod
    def register_listen_address(self, uri):
        """Will register publisher address to listen on

        NOTE Must be called prior to calling daemonize
        :parm uri:  uri to connect to
        :type string:   '<protocol>:address:port;....'
        :returns:   Boolean True if new
        """

    @abc.abstractmethod
    def unregister_listen_address(self, uri):
        """Will unregister publisher address to listen on

        NOTE Must be called prior to calling daemonize
        :parm uri:  uri to connect to
        :type string:   '<protocol>:address:port;....'
        """

    @abc.abstractmethod
    def run(self):
        """Method that will run in the Subscriber thread
        """

    @abc.abstractmethod
    def daemonize(self):
        """Start the Subscriber thread
        """

    @abc.abstractmethod
    def stop(self):
        """Stop the Subscriber thread
        """

    @abc.abstractmethod
    def register_topic(self, topic):
        """Add a topic to the subscriber listening list

        :param topic:  topic to listen to
        :type topic:   string
        :returns:   Boolean True if new
        """

    @abc.abstractmethod
    def unregister_topic(self, topic):
        """Remove a topic to the subscriber listening list

        :param topic:  topic to remove
        :type topic:   string
        """


class SubscriberAgentBase(SubscriberApi):

    def __init__(self):
        super(SubscriberAgentBase, self).__init__()
        self.topic_list = []
        self.uri_list = []

    def initialize(self, callback):
        self.db_changes_callback = callback
        self.daemon = df_utils.DFDaemon()

    def register_listen_address(self, uri):
        if uri not in self.uri_list:
            self.uri_list.append(uri)
            return True
        return False

    def unregister_listen_address(self, topic):
        self.uri_list.remove(topic)

    def daemonize(self):
        self.daemon.daemonize(self.run)

    @property
    def is_daemonize(self):
        return self.daemon.is_daemonize

    def stop(self):
        self.daemon.stop()

    def register_topic(self, topic):
        LOG.info(_LI('Register topic %s'), topic)
        if topic not in self.topic_list:
            self.topic_list.append(topic)
            return True
        return False

    def unregister_topic(self, topic):
        LOG.info(_LI('Unregister topic %s'), topic)
        self.topic_list.remove(topic)

    def set_subscriber_for_failover(self, sub, callback):
        pass

    def register_hamsg_for_db(self):
        pass

    def process_ha(self):
        pass


class TableMonitor(object):

    def __init__(self, table_name, driver, publisher, polling_time=10):
        self._driver = driver
        self._publisher = publisher
        self._polling_time = polling_time
        self._daemon = df_utils.DFDaemon()
        self._table_name = table_name

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def run(self):
        cache = {}
        while True:
            try:
                eventlet.sleep(self._polling_time)
                cache = self._poll_once(cache)
            except Exception:
                LOG.exception(_LE("Error when polling table %s"),
                              self._table_name)

    def _poll_once(self, old_cache):
        """Create a new cache and send events for changes from the old cache"""
        new_cache = {}
        for entry_key in self._driver.get_all_keys(self._table_name):
            entry_value = self._driver.get_key(
                self._table_name,
                entry_key)
            if entry_value is None:
                continue
            old_value = old_cache.pop(entry_key, None)
            if old_value is None:
                self._send_event('create', entry_key, entry_value)
            elif old_value != entry_value:
                self._send_event('set', entry_key, entry_value)
            new_cache[entry_key] = entry_value
        for entry_key in old_cache:
            self._send_event('delete', entry_key, None)
        return new_cache

    def _send_event(self, action, entry_id, entry_value):
        db_update = db_common.DbUpdate(
            self._table_name,
            entry_id,
            action,
            entry_value,
        )
        self._publisher.send_event(db_update)


class StalePublisherMonitor(TableMonitor):

    def __init__(self, driver, publisher, timeout, polling_time=10):
        super(StalePublisherMonitor, self).__init__(
            models.Publisher.table_name,
            driver,
            publisher,
            polling_time
        )
        self._timeout = timeout
        self._uuid = generate_publisher_uuid()

    def _poll_once(self, old_cache):
        """Scan for stale entries of other publishers"""
        for entry_key in self._driver.get_all_keys(self._table_name):
            publisher_json = self._driver.get_key(self._table_name, entry_key)
            if publisher_json is None:
                continue
            publisher = jsonutils.loads(publisher_json)
            if publisher['id'] == self._uuid:
                continue
            last_activity_timestamp = publisher['last_activity_timestamp']
            if last_activity_timestamp < time.time() - self._timeout:
                LOG.info(_LI('Removing publisher %s'), publisher_json)
                try:
                    self._driver.delete_key(self._table_name, entry_key)
                except exceptions.DBKeyNotFound:
                    # Publisher already deleted. Ignore.
                    pass
        return super(StalePublisherMonitor, self)._poll_once(old_cache)
