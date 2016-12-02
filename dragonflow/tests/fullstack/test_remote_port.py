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

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import constants as test_const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestRemotePort(test_base.DFTestBase):

    def test_remote_port(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'network1'})
        self.assertTrue(network.exists())

        subnet_info = {'network_id': network_id,
                       'cidr': '192.168.150.0/24',
                       'gateway_ip': '192.168.150.1',
                       'ip_version': 4,
                       'name': 'subnet1',
                       'enable_dhcp': True}
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)
        self.assertTrue(subnet.exists())

        port = self.store(objects.PortTestObj(
                self.neutron, self.nb_api, network_id))
        port_body = {
                'admin_state_up': True,
                'name': 'port1',
                'network_id': network_id,
                'binding:profile': {
                    'port_key': 'remote_port',
                    'host_ip': '10.10.10.10'
                }
        }
        port.create(port=port_body)
        self.assertTrue(port.exists())

        time.sleep(test_const.DEFAULT_CMD_TIMEOUT)
        ovsdb = utils.OvsDBParser()
        network_obj = network.get_network()['network']
        network_type = network_obj['provider:network_type']
        segmentation_id = network_obj['provider:segmentation_id']
        ofport = ovsdb.get_tunnel_ofport(network_type)
        port_unique_key = port.get_logical_port().get_unique_key()

        match = "reg7=" + str(hex(port_unique_key))
        action = ("set_field:10.10.10.10" +
                  "->tun_dst,set_field:" + str(hex(segmentation_id)) +
                  "->tun_id,output:" + str(ofport))
        ovs = utils.OvsFlowsParser()
        matched = False
        for flow in ovs.dump(self.integration_bridge):
            if flow['table'] == str(const.EGRESS_TABLE):
                if match in flow['match']:
                    matched = True
                    self.assertEqual(action, flow['actions'])

        if not matched:
            raise Exception("Can't find flows for remote port!")
