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

import re

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestL2Multicast(test_base.DFTestBase):

    def _get_metadata_id(self, flows, ip, mac):
        for flow in flows:
            if flow['table'] == str(const.L3_PROACTIVE_LOOKUP_TABLE):
                if 'nw_dst=' + ip in flow['match'] and mac in flow['actions']:
                    m = re.search('metadata=0x([0-9a-f]+)', flow['match'])
                    if m:
                        return m.group(1)
        return None

    def _get_vm_port(self, ip, mac):
        ports = self.nb_api.get_all_logical_ports()
        for port in ports:
            if port.get_device_owner() == 'compute:None':
                if port.get_ip() == ip and port.get_mac() == mac:
                    return port
        return None

    """
    Ethernet frames with a value of 1 in the least-significant bit of the first
    octet of the destination address are treated as multicast frames and are
    flooded to all points on the network.
    https://en.wikipedia.org/wiki/Multicast_address
    """
    def _check_multicast_rule(self, flows, metadataid, tunnel_key_hex):
        check = 'set_field:' + tunnel_key_hex + '->reg7,resubmit(,' + \
            str(const.EGRESS_TABLE) + ')'
        for flow in flows:
            if flow['table'] == str(const.L2_LOOKUP_TABLE):
                if ('dl_dst=01:00:00:00:00:00/01:00:00:00:00:00' in
                    flow['match']):
                    if 'metadata=0x' + metadataid in flow['match']:
                        if check in flow['actions']:
                            return flow
        return None

    def test_vm_multicast(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
        subnet = {'network_id': network_id,
            'cidr': '10.200.0.0/24',
            'gateway_ip': '10.200.0.1',
            'ip_version': 4,
            'name': 'private',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})

        ovs = utils.OvsFlowsParser()
        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)
        self.assertIsNotNone(vm.server.addresses['private'])
        mac = vm.server.addresses['private'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        metadataid = utils.wait_until_is_and_return(
            lambda: self._get_metadata_id(ovs.dump(self.integration_bridge),
                                          ip, mac),
            exception=Exception('Metadata id was not found in OpenFlow rules')
        )
        port = utils.wait_until_is_and_return(
            lambda: self._get_vm_port(ip, mac),
            exception=Exception('No port assigned to VM')
        )
        tunnel_key = port.get_tunnel_key()
        tunnel_key_hex = hex(tunnel_key)
        r = self._check_multicast_rule(ovs.dump(self.integration_bridge),
                                       metadataid, tunnel_key_hex)
        self.assertIsNotNone(r)
        vm.close()
        network.close()
