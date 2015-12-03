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
        :type args:        dictionary of <string, string>
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
    def get_key(self, table, key):
        """Get the value of a specific key in a table

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :returns:          string - the key value
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def set_key(self, table, key, value):
        """Set a specific key in a table with value

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param value:      value to set for the key
        :type value:       string
        :returns:          None
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def create_key(self, table, key, value):
        """Create a specific key in a table with value

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :param value:      value to set for the created key
        :type value:       string
        :returns:          None
        """

    @abc.abstractmethod
    def delete_key(self, table, key):
        """Delete a specific key from a table

        :param table:      table name
        :type table:       string
        :param key:        key name
        :type key:         string
        :returns:          None
        :raises:           DragonflowException.DBKeyNotFound if key not found
        """

    @abc.abstractmethod
    def get_all_entries(self, table):
        """Returns a list of all table entries values

        :param table:      table name
        :type table:       string
        :returns:          list of values
        """

    @abc.abstractmethod
    def get_all_keys(self, table):
        """Returns a list of all table entries keys

        :param table:      table name
        :type table:       string
        :returns:          list of keys
        """

    @abc.abstractmethod
    def register_notification_callback(self, callback):
        """Register for DB changes notifications, DB driver should
           call callback method for every change.
           DB driver is responsible to start the appropriate listener
           threads on DB changes and send changes to callback.

        :param callback:  callback method to call for every db change
        :type callback :  callback method of type:
                          callback(table, key, action, value)
                          table - table name
                          key - object key
                          action = 'create' / 'set' / 'delete'
                          value = new object value
        :returns:         None
        """

    @abc.abstractmethod
    def allocate_unique_key(self):
        """Allocate a unique id in the system
           Used to allocate ports unique numbers

        :returns:     Unique id
        """
