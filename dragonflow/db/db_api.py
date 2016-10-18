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
import six


@six.add_metaclass(abc.ABCMeta)
class DbApi(object):

    @abc.abstractmethod
    def initialize(self, db_ip, db_port, **args):
        """Initialize the DB client

        :param db_ip:      DB server IP address
        :type db_ip:       string
        :param db_port:    DB server port number
        :type db_port:     int
        :param args:       Additional args that were read from configuration
                           file
        :type args:        dictionary of <string, object>
        :returns:          None
        """

    @abc.abstractmethod
    def support_publish_subscribe(self):
        """Return if this DB support publish-subscribe

           If this method returns True, the DB driver needs to
           implement register_notification_callback() API in this class

        :returns:          boolean (True or False)
        """

    @abc.abstractmethod
    def create_table(self, table):
        """Create a table

        :param table:      table name
        :type table:       string
        :returns:          None
        """

    @abc.abstractmethod
    def delete_table(self, table):
        """Delete a table

        :param table:      table name
        :type table:       string
        :returns:          None
        """

    @abc.abstractmethod
    def get_key(self, table, key, topic=None):
        """Get the value of a specific key in a table

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param topic:      topic for key
        :type topic:       string
        :returns:          string - the key value
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def set_key(self, table, key, value, topic=None):
        """Set a specific key in a table with value

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param value:      value to set for the key
        :type value:       string
        :param topic:      topic for key
        :type topic:       string
        :returns:          None
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def create_key(self, table, key, value, topic=None):
        """Create a specific key in a table with value

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param value:      value to set for the created key
        :type value:       string
        :param topic:      topic for key
        :type topic:       string
        :returns:          None
        """

    @abc.abstractmethod
    def delete_key(self, table, key, topic=None):
        """Delete a specific key from a table

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param topic:      topic for key
        :type topic:       string
        :returns:          None
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def get_all_entries(self, table, topic=None):
        """Returns a list of all table entries values

        :param table:      table name
        :type table:       string
        :param topic:      get only entries matching this topic
        :type topic:       string
        :returns:          list of values
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def get_all_keys(self, table, topic=None):
        """Returns a list of all table entries keys

        :param table:      table name
        :type table:       string
        :param topic:      get all keys matching this topic
        :type topic:       string
        :returns:          list of keys
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def register_notification_callback(self, callback, topics=None):
        """Register for DB changes notifications, DB driver should
           call callback method for every change.
           DB driver is responsible to start the appropriate listener
           threads on DB changes and send changes to callback.

           Returning the callback with action=='sync' will trigger
           a full sync process by the controller
           (Reading all entries for all tables)

        :param callback:  callback method to call for every db change
        :type callback :  callback method of type:
                          callback(table, key, action, value)
                          table - table name
                          key - object key
                          action = 'create' / 'set' / 'delete' / 'sync'
                          value = new object value
        :param topics:    topics to register for DB notifications
        :type topics :     list of strings (topics)
        :returns:         None
        """

    @abc.abstractmethod
    def register_topic_for_notification(self, topic):
        """Register new topic, start receiving updates on this topic

        :param topic:  topic to register for DB notifications
        :type topic :  string
        :returns:      None
        """

    @abc.abstractmethod
    def unregister_topic_for_notification(self, topic):
        """Un-register topic, stop receiving updates on this topic

        :param topic:  topic to un-register for DB notifications
        :type topic :  string
        :returns:      None
        """

    @abc.abstractmethod
    def allocate_unique_key(self, table):
        """Allocate a unique id in the controller

        :table:       The name of resource table
        :returns:     Unique id
        """

    @abc.abstractmethod
    def process_ha(self):
        """Process HA functions

        :returns:    None
        """

    @abc.abstractmethod
    def set_neutron_server(self, is_neutron_server):
        """Set neutron server flag

        :returns:    None
        """
