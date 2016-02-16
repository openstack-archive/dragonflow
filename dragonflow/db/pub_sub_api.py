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
import eventlet
import msgpack
import six

from oslo_log import log as logging

from dragonflow._i18n import _LW
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common

LOG = logging.getLogger(__name__)

eventlet.monkey_patch(socket=False)

def pack_message(self, message):
    data = None
    try:
        data = msgpack.packb(message, encoding='utf-8')
    except Exception as e:
        LOG.warning(e)
    return data

def unpack_message(self, message):
    entry = None
    try:
        entry = msgpack.unpackb(message, encoding='utf-8')
    except Exception as e:
        LOG.warning(e)
    return entry


@six.add_metaclass(abc.ABCMeta)
class PubSubApi(object):

    @abc.abstractmethod
    def get_publisher(self):
        """Return a Publisher Driver Object

        :returns: an PublisherApi Object
        """

    @abc.abstractmethod
    def get_subscriber(self):
        """Return a Subscriber Driver Object

        :returns: an PublisherApi Object
        """


@six.add_metaclass(abc.ABCMeta)
class PublisherApi(object):

    @abc.abstractmethod
    def initialize(self, endpoint, trasport_proto, **args):
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
    def run(self):
        """Method that will run in the Subscriber thread
        """

    @abc.abstractmethod
    def daemonize(self):
        """Start the Subscriber thread
        """

    @abc.abstractmethod
    def stop(self):
        """Stop the Publisher thread
        """


@six.add_metaclass(abc.ABCMeta)
class SubscriberApi(object):

    @abc.abstractmethod
    def initialize(self, callback, **args):
        """Initialize the DB client

        :param callback:  callback method to call for every db change
        :type callback :  callback method of type:
                          callback(table, key, action, value)
                          table - table name
                          key - object key
                          action = 'create' / 'set' / 'delete' / 'sync'
                          value = new object value
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
        """

    @abc.abstractmethod
    def unregister_topic(self, topic):
        """Remove a topic to the subscriber listening list

        :param topic:  topic to remove
        :type topic:   string
        """


class PublisherAgentBase(PublisherApi):

    def __init__(self):
        super(PublisherAgentBase, self).__init__()
        self.endpoint = None
        self.trasport_proto = None
        self.daemon = None
        self.config = None

    def initialize(self, endpoint, trasport_proto, config=None, **args):
        self.endpoint = endpoint
        self.trasport_proto = trasport_proto
        self.daemon = df_utils.DFDaemon()
        self.config = config

    def daemonize(self):
        self.daemon.daemonize(self.run)

    @property
    def is_daemonize(self):
        return self.daemon.is_daemonize

    def stop(self):
        self.daemon.stop()


class SubscriberAgentBase(SubscriberApi):

    def __init__(self):
        super(SubscriberAgentBase, self).__init__()
        self.topic_list = []
        self.uri_list = []
        self.topic_list.append(db_common.SEND_ALL_TOPIC)

    def initialize(self, callback, config=None, **args):
        self.db_changes_callback = callback
        self.daemon = df_utils.DFDaemon()
        self.config = config

    def register_listen_address(self, uri):
        self.uri_list.append(uri)

    def daemonize(self):
        self.daemon.daemonize(self.run)

    @property
    def is_daemonize(self):
        return self.daemon.is_daemonize

    def stop(self):
        self.daemon.stop()

    def register_topic(self, topic):
        self.topic_list.append(topic)

    def unregister_topic(self, topic):
        self.topic_list.remove(topic)

    def unregister_listen_address(self, topic):
        self.uri_list.remove(topic)


class TableMonitor(object):
    def __init__(self, table_name, driver, publisher, polling_time=10):
        self._driver = driver
        self._publisher = publisher
        self._polling_time = polling_time
        self._daemon = df_utils.DFDaemon()
        self._table_name = table_name
        pass

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def run(self):
        cache = {}
        while True:
            try:
                eventlet.sleep(self._polling_time)
                cache = self._update_cache(cache)
            except Exception as e:
                LOG.warning(_LW("Error when polling table {}: {}").format(
                    self._table_name,
                    repr(e)
                ))

    def _update_cache(self, old_cache):
        """Create a new cache and send events for changes from the old cache"""
        new_cache = {}
        for entry_key in self._driver.get_all_keys(self._table_name):
            entry_value = self._driver.get_key(
                self._table_name,
                entry_key)
            old_value = old_cache.pop(entry_key, None)
            if old_value is None:
                self._send_event('create', entry_key, entry_value)
            elif old_value != entry_value:
                    self._send_event('update', entry_key, entry_value)
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
