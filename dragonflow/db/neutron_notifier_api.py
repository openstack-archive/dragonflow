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
class NeutronNotifierDriver(object):
    # NeutronNotifierDriver implements notification mechanism from
    # Dragonflow controller to northbound neutron server.

    @abc.abstractmethod
    def initialize(self, nb_api, is_neutron_server):
        """Initialise the NeutronNotifierDriver both in neutron server and
           compute node.

        :nb_api:               nb_api driver
        :is_neutron_server     Neutron server or compute
        :return:    None
        """

    @abc.abstractmethod
    def notify_neutron_server(self, table, key, action, value, topic):
        """Notify the change to neutron server. Note that this method
           will run in neutron server.

        :param table:    which db model
        :param key:      the id of db model data
        :param action:   the action of data, create/update/delete
        :param value:    the value of db model data
        :param topic:    the topic of neutron server's corresponding listener
        :return:         None
        """
