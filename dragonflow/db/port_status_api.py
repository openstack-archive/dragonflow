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
class PortStatusDriver(object):
    # PortStatus implements port status update southbound
    # notification mechanism.

    @abc.abstractmethod
    def initialize(self, mech_driver, nb_api,
                   pub, sub, is_neutron_server):
        """Initialise the portstatus both in server
           compute node

        :param mech_driver:    neutron ml2 driver
        :nb_api:               nb_api driver
        :pub:                  publisher
        :sub:                  subscriber
        :is_neutron_server     server or compute
        :return:    None
        """

    @abc.abstractmethod
    def notify_port_status(self, ovs_port, status):
        """notify port status changes to server

        :param ovs_port:    which port status changed
        :param status:      notify port status up or down
        :return:            None
        """
