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
from oslo_config import cfg

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

SNAT_APP_NAME = 'chassis_snat'


class TestSnatFlows(test_base.DFTestBase):
    apps_list = [SNAT_APP_NAME]

    def _check_if_app_enabled(self):
        return SNAT_APP_NAME in cfg.CONF.df.apps_list

    def _check_port_based_flows(self,
                                flows, hex_port_key, external_host_mac, mac):
        match = 'ct_mark=' + hex_port_key + ',ip'
        action = 'set_field:' + external_host_mac + '->eth_src' \
            ',set_field:' + mac + '->eth_dst' \
            ',load:' + hex_port_key + '->NXM_NX_REG7[]' + \
            ',move:NXM_NX_CT_LABEL[0..31]->NXM_OF_IP_DST[]' + \
            ',goto_table:' + str(const.INGRESS_DISPATCH_TABLE)

        port_based_ingress = None
        for flow in flows:
            if flow['table'] == str(const.INGRESS_SNAT_TABLE):
                if (match in flow['match']):
                    if action in flow['actions']:
                        port_based_ingress = True

        return {'port_based_ingress': port_based_ingress}

    def test_port_based_flows(self):
        if not self._check_if_app_enabled():
            return

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = {'network_id': network_id,
                  'cidr': '10.200.0.0/24',
                  'gateway_ip': '10.200.0.1',
                  'ip_version': 4,
                  'name': 'private',
                  'enable_dhcp': True}

        external_host_ip = cfg.CONF.df.external_host_ip
        self.assertIsNotNone(external_host_ip)
        split_ip = external_host_ip.split('.')
        ip2mac = '{:02x}:{:02x}:{:02x}:{:02x}'.format(*map(int, split_ip))
        external_host_mac = const.CHASSIS_MAC_PREFIX + ip2mac

        subnet = self.neutron.create_subnet({'subnet': subnet})
        self.assertIsNotNone(subnet)

        # Create VM
        ovs = utils.OvsFlowsParser()
        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)

        mac = vm.get_first_mac()
        self.assertIsNotNone(mac)

        port = utils.wait_until_is_and_return(
            lambda: utils.find_logical_port(self.nb_api, ip, mac),
            exception=Exception('No port assigned to VM')
        )
        port_key = port.unique_key
        r = self._check_port_based_flows(
            ovs.dump(self.integration_bridge),
            hex(port_key),
            external_host_mac,
            mac)
        for key, value in r.items():
            self.assertIsNotNone(value, key)

        vm.server.stop()
        vm.close()
        network.close()
        return None
