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
import multiprocessing
import six

from oslo_log import log as logging
LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


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
    def initialize(self, ip, is_plugin, publish_port, **args):
        """Initialize the DB client

        :param ip:      Publiser IP address
        :type ip:       string
        :param is_plugin: Publisher is part of the neutron server Plugin
        :type is_plugin: boolean (True or False)
        :param publish_port:    Publisher server port number
        :type publisher_port:     int
        :param args:       Additional args that were read from configuration
                           file
        :type args:        dictionary of <string, object>
        :returns:          None
        """

    @abc.abstractmethod
    def daemonize(self):
        """Start the Publisher thread
        """

    @abc.abstractmethod
    def stop(self):
        """Stop the Publisher thread
        """

    @abc.abstractmethod
    def send_event(self, update):
        """Publish the update

        :param update:  Encapsulates a Publisher update
        :type update:   DbUpdate object
        :returns:          None
        """


@six.add_metaclass(abc.ABCMeta)
class SubscriberApi(object):

    @abc.abstractmethod
    def initialize(self, ip, callback, plugin_port, cont_port, **args):
        """Initialize the DB client

        :param ip:      Subscriber IP address
        :type ip:       string
        :param callback:  callback method to call for every db change
        :type callback :  callback method of type:
                          callback(table, key, action, value)
                          table - table name
                          key - object key
                          action = 'create' / 'set' / 'delete' / 'sync'
                          value = new object value
        :param plugin_port: Subscription port for plugin Events
        :type plugin_port:     int
        :param controller_port: Subscription port for controllers Events
        :type controller_port:     int
        :param args:       Additional args that were read from configuration
                           file
        :type args:        dictionary of <string, object>
        :returns:          None
        """

    @abc.abstractmethod
    def daemonize(self):
        """Start the Subscriber thread
        """

    @abc.abstractmethod
    def stop(self):
        """Stop the Subscriber thread
        """


class PublisherAgentBase(PublisherApi):

    def __init__(self):
        super(PublisherAgentBase, self).__init__()

    def initialize(self, ip, is_plugin, publish_port=8866, **args):
        self.ip = ip
        self.port = publish_port
        self.pub_socket = None
        self.pool = eventlet.GreenPool()
        if is_plugin:
            self._queue = multiprocessing.Queue()
        else:
            self._queue = eventlet.queue.PriorityQueue()

        self.is_daemonize = False
        self.pub_thread = None
        self.is_plugin = is_plugin

    def daemonize(self):
        self.is_daemonize = True
        self.pub_thread = self.pool.spawn(self.run)
        eventlet.sleep(0)

    def stop(self):
        if self.pub_thread:
            eventlet.greenthread.kill(self.pub_thread)
            eventlet.sleep(0)

    def pack_message(self, message):
        data = None
        try:
            data = msgpack.packb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return data

    def send_event(self, update):
        if self.is_daemonize:
            #NOTE(gampel)In this reference implementation we develop a trigger
            #based pub sub without sending the value mainly in order to avoid
            #consistency issues in th cost of extra latency i.e get
            update.value = None
            self._queue.put(update)
            eventlet.sleep(0)


class SubscriberAgentBase(SubscriberApi):

    def __init__(self):
        super(SubscriberAgentBase, self).__init__()

    def initialize(self, ip, callback, plugin_port=8866, cont_port=8867):
        self.db_changes_callback = callback
        self.ip = ip
        self.plugin_updates_port = plugin_port
        self.controllers_updates_port = cont_port
        self.sub_thread = None
        self.pool = eventlet.GreenPool()

    def unpack_message(self, message):
        entry = None
        try:
            entry = msgpack.unpackb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return entry

    def daemonize(self):
        self.sub_thread = self.pool.spawn_n(
                                    self.run,
                                    "Plugin",
                                    self.plugin_updates_port)
        eventlet.sleep(0)

    def stop(self):
        if self.sub_thread:
            eventlet.greenthread.kill(self.sub_thread)
            eventlet.sleep(0)
