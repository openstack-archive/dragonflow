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

from dragonflow.common import utils as df_utils

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
    def initialize(self, ip, is_neutron_server, publish_port, **args):
        """Initialize the DB client

        :param ip:      Publiser IP address
        :type ip:       string
        :param is_neutron_server: Publisher is part of the neutron server
        :type is_neutron_server: boolean (True or False)
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
    def run(self):
        """Method that will run in the Publisher thread
        """

    @abc.abstractmethod
    def stop(self):
        """Stop the Publisher thread
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
    def add_topic(self, topic):
        """Add a topic to the subsciber listening list

        :param topic:  topic to listen to
        :type topic:   string
        """


class PublisherAgentBase(PublisherApi):

    def initialize(self, ip, is_neutron_server, publish_port=8866, **args):
        self.ip = ip
        self.port = publish_port
        self.pub_socket = None
        if is_neutron_server:
            self._queue = multiprocessing.Queue()
        else:
            self._queue = eventlet.queue.PriorityQueue()

        self.is_neutron_server = is_neutron_server
        self.daemon = df_utils.DFDaemon()

    def pack_message(self, message):
        data = None
        try:
            data = msgpack.packb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return data

    def send_event(self, update, topic=None):
        if self.is_daemonize:
            #NOTE(gampel)In this reference implementation we develop a trigger
            #based pub sub without sending the value mainly in order to avoid
            #consistency issues in th cost of extra latency i.e get
            update.value = None
            if topic:
                update.topic = topic
            self._queue.put(update)
            eventlet.sleep(0)

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
        self.topic_list.append(b'D')

    def initialize(self, ip, callback, plugin_port=8866, cont_port=8867):
        self.db_changes_callback = callback
        self.ip = ip
        self.plugin_updates_port = plugin_port
        self.controllers_updates_port = cont_port
        self.daemon = df_utils.DFDaemon()

    def unpack_message(self, message):
        entry = None
        try:
            entry = msgpack.unpackb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return entry

    def daemonize(self):
        self.daemon.daemonize(self.run)

    @property
    def is_daemonize(self):
        return self.daemon.is_daemonize

    def stop(self):
        self.daemon.stop()

    def add_topic(self, topic):
        self.topic_list.append(topic)
