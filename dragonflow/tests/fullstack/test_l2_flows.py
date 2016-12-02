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

from oslo_config import cfg

import ConfigParser
from dragonflow.controller.common import constants as const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

ML2_CONF_INI = '/etc/neutron/plugins/ml2/ml2_conf.ini'
L2_ML2_APP_NAME = 'l2_app.L2App'
VLAN_MIN_DEFAULT = 2


class TestL2FLows(test_base.DFTestBase):
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

    def test_tunnel_network_flows(self):
        if self._check_l2_ml2_app_enable() is False:
            return

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
        network_params = network.get_network()
        segmentation_id = network_params['network']['provider:segmentation_id']
        subnet = {'network_id': network_id,
            'cidr': '10.200.0.0/24',
            'gateway_ip': '10.200.0.1',
            'ip_version': 4,
            'name': 'private',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})
        self.assertIsNotNone(subnet)

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
        tunnel_key = port.get_unique_key()
        tunnel_key_hex = hex(tunnel_key)
        n_type = network.get_network()['network']['provider:network_type']
        ovsdb = utils.OvsDBParser()
        ofport = ovsdb.get_tunnel_ofport(n_type)
        r = self._check_tunnel_flows(ovs.dump(self.integration_bridge),
                                     metadataid,
                                     hex(segmentation_id),
                                     tunnel_key_hex,
                                     mac, ofport)
        self.assertIsNotNone(r)
        vm.close()
        network.close()

    def test_vlan_network_flows(self):
        if self._check_l2_ml2_app_enable() is False:
            return

        physical_network, vlan_min = self._parse_network_vlan_ranges()
        if physical_network is None or vlan_min is None:
            self.assertIsNotNone(None)
            return

        # Create network
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_params = {"name": "vlan_1",
                          "provider:network_type": "vlan",
                          "provider:physical_network": physical_network,
                          "provider:segmentation_id": vlan_min}
        network_id = network.create(network=network_params)

        # Create subnet
        subnet_params = {'network_id': network_id,
                         'cidr': '100.64.0.0/24',
                         'gateway_ip': '10.64.0.1',
                         'ip_version': 4,
                         'name': 'private',
                         'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet_params})
        self.assertIsNotNone(subnet)

        # Create VM
        ovs = utils.OvsFlowsParser()
        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)
        mac = vm.get_first_mac()
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
        port_key = port.get_unique_key()
        port_key_hex = hex(port_key)

        r = self._check_vlan_flows(ovs.dump(self.integration_bridge),
                                   metadataid,
                                   vlan_min,
                                   port_key_hex,
                                   mac)
        self.assertIsNotNone(r)
        vm.server.stop()
        vm.close()
        network.close()

    def _check_tunnel_flows(self, flows, metadtata, segmentation_id,
                            port_key_hex, mac, tunnel_ofport):
        l2_lookup_unicast_match = 'metadata=0x' + metadtata + \
                                 ',dl_dst=' + mac
        l2_lookup_unicast_action = 'goto_table:' + \
                                   str(const.EGRESS_TABLE)
        l2_lookup_multicast_match = 'metadata=0x' + metadtata + ',dl_dst=' + \
                                    '01:00:00:00:00:00/01:00:00:00:00:00'
        l2_lookup_multicast_action = 'set_field:' + port_key_hex + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')' + \
                                     ',set_field:0' + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')'

        ingress_match = ('tun_id=' + str(segmentation_id)
                         + ",in_port=" + str(tunnel_ofport))
        ingress_action = 'set_field:0x' + metadtata + '->metadata,' + \
                         'goto_table:' + \
                         str(const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        l2_lookup_unicast_check = None
        l2_lookup_multicast_check = None
        ingress_check = None

        for flow in flows:
            if flow['table'] == str(const.L2_LOOKUP_TABLE):
                if (l2_lookup_multicast_match in flow['match']):
                    if l2_lookup_multicast_action in flow['actions']:
                        l2_lookup_multicast_check = True
                if (l2_lookup_unicast_match in flow['match']):
                    if l2_lookup_unicast_action in flow['actions']:
                        l2_lookup_unicast_check = True

            if flow['table'] == str(
                    const.INGRESS_CLASSIFICATION_DISPATCH_TABLE):
                if (ingress_match in flow['match']):
                    if ingress_action in flow['actions']:
                        ingress_check = True

        if (l2_lookup_multicast_check is None or
                l2_lookup_unicast_check is None or
                ingress_check is None):
            return None

        return True

    def _check_vlan_flows(self, flows, metadtata, segmentation_id,
                          port_key_hex, mac):
        l2_lookup_unicast_match = 'metadata=0x' + metadtata + \
                                 ',dl_dst=' + mac
        l2_lookup_unicast_action = 'goto_table:' + \
                                   str(const.EGRESS_TABLE)
        l2_lookup_unknown_match = 'metadata=0x' + metadtata + \
                                  ',dl_dst=00:00:00:00:00:00/01:00:00:00:00:00'
        l2_lookup_unkown_action = 'goto_table:' + \
                                  str(const.EGRESS_TABLE)
        l2_lookup_multicast_match = 'metadata=0x' + metadtata + ',dl_dst=' + \
                                    '01:00:00:00:00:00/01:00:00:00:00:00'
        l2_lookup_multicast_action = 'set_field:' + port_key_hex + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')' + \
                                     ',set_field:0' + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')'

        egress_match = 'metadata=0x' + metadtata
        egress_action = 'push_vlan:0x8100,set_field:' + \
                        str(int(segmentation_id) + 4096) + \
                        "->vlan_vid,goto_table:" + \
                        str(const.EGRESS_EXTERNAL_TABLE)

        ingress_match = 'dl_vlan=' + str(segmentation_id)
        ingress_action = 'set_field:0x' + metadtata + '->metadata,' \
                                                      'pop_vlan,goto_table:' + \
                         str(const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        l2_lookup_unicast_check = None
        l2_lookup_multicast_check = None
        l2_lookup_unkown_check = None
        egress_check = None
        ingress_check = None

        for flow in flows:
            if flow['table'] == str(const.L2_LOOKUP_TABLE):
                if (l2_lookup_multicast_match in flow['match']):
                    if l2_lookup_multicast_action in flow['actions']:
                        l2_lookup_multicast_check = True
                if (l2_lookup_unicast_match in flow['match']):
                    if l2_lookup_unicast_action in flow['actions']:
                        l2_lookup_unicast_check = True
                if (l2_lookup_unknown_match in flow['match']):
                    if l2_lookup_unkown_action in flow['actions']:
                        l2_lookup_unkown_check = True
            if flow['table'] == str(const.EGRESS_TABLE):
                if (egress_match in flow['match']):
                    if egress_action in flow['actions']:
                        egress_check = True

            if flow['table'] == str(
                    const.INGRESS_CLASSIFICATION_DISPATCH_TABLE):
                if (ingress_match in flow['match']):
                    if ingress_action in flow['actions']:
                        ingress_check = True

        if (l2_lookup_multicast_check is None or
                l2_lookup_unicast_check is None or
                l2_lookup_unkown_check is None or
                egress_check is None or
                ingress_check is None):

            return None

        return True

    def test_flat_network_flows(self):
        if self._check_l2_ml2_app_enable() is False:
            return

        physical_network = self._parse_flat_network()
        if not physical_network:
            self.assertIsNotNone(None)
            return

        # Create network
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_params = {"name": "vlan_1",
                          "provider:network_type": "flat",
                          "provider:physical_network": physical_network}
        network_id = network.create(network=network_params)

        # Create subnet
        subnet_params = {'network_id': network_id,
                         'cidr': '100.64.0.0/24',
                         'gateway_ip': '10.64.0.1',
                         'ip_version': 4,
                         'name': 'private',
                         'enable_dhcp': True}

        subnet = self.neutron.create_subnet({'subnet': subnet_params})
        self.assertIsNotNone(subnet)

        # Create VM
        ovs = utils.OvsFlowsParser()
        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)

        mac = vm.get_first_mac()
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
        port_key = port.get_unique_key()
        port_key_hex = hex(port_key)
        r = self._check_flat_flows(ovs.dump(self.integration_bridge),
                                   metadataid, port_key_hex, mac)
        self.assertIsNotNone(r)
        vm.server.stop()
        vm.close()
        network.close()
        return None

    def _check_flat_flows(self, flows, metadtata,
                          port_key_hex, mac):
        l2_lookup_unicast_match = 'metadata=0x' + metadtata + \
                                 ',dl_dst=' + mac
        l2_lookup_unicast_action = 'goto_table:' + \
                                   str(const.EGRESS_TABLE)
        l2_lookup_unkown_match = 'metadata=0x' + metadtata + \
                                 ',dl_dst=00:00:00:00:00:00/01:00:00:00:00:00'
        l2_lookup_unkown_action = 'goto_table:' + \
                                  str(const.EGRESS_TABLE)
        l2_lookup_multicast_match = 'metadata=0x' + metadtata + ',dl_dst=' + \
                                    '01:00:00:00:00:00/01:00:00:00:00:00'
        l2_lookup_multicast_action = 'set_field:' + port_key_hex + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')' + \
                                     ',set_field:0' + \
                                     '->reg7,resubmit(,' + \
                                     str(const.EGRESS_TABLE) + ')'

        egress_match = 'metadata=0x' + metadtata
        egress_action = 'goto_table:' + \
                        str(const.EGRESS_EXTERNAL_TABLE)
        ingress_match = 'vlan_tci=0x0000/0x1fff'
        ingress_action = 'set_field:0x' + metadtata + \
                         '->metadata,goto_table:' + \
                         str(const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)
        l2_lookup_unicast_check = None
        l2_lookup_multicast_check = None
        l2_lookup_unkown_check = None
        ingress_check = None
        egress_check = None

        for flow in flows:
            if flow['table'] == str(const.L2_LOOKUP_TABLE):
                if (l2_lookup_multicast_match in flow['match']):
                    if l2_lookup_multicast_action in flow['actions']:
                        l2_lookup_multicast_check = True
                if (l2_lookup_unicast_match in flow['match']):
                    if l2_lookup_unicast_action in flow['actions']:
                        l2_lookup_unicast_check = True
                if (l2_lookup_unkown_match in flow['match']):
                    if l2_lookup_unkown_action in flow['actions']:
                        l2_lookup_unkown_check = True
            if flow['table'] == str(const.EGRESS_TABLE):
                if (egress_match in flow['match']):
                    if egress_action in flow['actions']:
                        egress_check = True

            if flow['table'] == str(
                    const.INGRESS_CLASSIFICATION_DISPATCH_TABLE):
                if (ingress_match in flow['match']):
                    if ingress_action in flow['actions']:
                        ingress_check = True

        if (l2_lookup_multicast_check is None or
                l2_lookup_unicast_check is None or
                l2_lookup_unkown_check is None or
                egress_check is None or
                ingress_check is None):
            return None
        return True

    def _get_config_values(self, section, key):
        readhandle = None
        value = None
        try:
            config = ConfigParser.ConfigParser()
            readhandle = open(ML2_CONF_INI, 'r')
            config.readfp(readhandle)
            value = config.get(section, key)
        except Exception:
            value = None

        if readhandle is not None:
            try:
                readhandle.close()
            except Exception:
                return value
        return value

    def _check_l2_ml2_app_enable(self):
        apps_list = cfg.CONF.df.apps_list
        if L2_ML2_APP_NAME in apps_list:
            return True
        return False

    def _parse_network_vlan_ranges(self):
        network_vlan_ranges = self._get_config_values('ml2_type_vlan',
                                                      'network_vlan_ranges')

        if network_vlan_ranges is None:
            return None

        network_vlan_range_list = network_vlan_ranges.split(',')
        if not network_vlan_range_list:
            return None

        network_vlan_range = network_vlan_range_list[0]
        if ':' in network_vlan_range:
            try:
                physical_network, vlan_min, vlan_max = \
                    network_vlan_range.split(':')
            except ValueError:
                return None
        else:
            physical_network = network_vlan_range
            vlan_min = VLAN_MIN_DEFAULT

        return physical_network, vlan_min

    def _parse_flat_network(self):
        flat_networks = self._get_config_values('ml2_type_flat',
                                                'flat_networks')
        if flat_networks is None:
            return None

        flat_networks_list = flat_networks.split(',')
        if not flat_networks_list:
            return None

        flat_network = flat_networks_list[0]

        physical_network = 'phynet1'
        if flat_network != '*':
            physical_network = flat_network

        return physical_network

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
        tunnel_key = port.get_unique_key()
        tunnel_key_hex = hex(tunnel_key)
        r = self._check_multicast_rule(ovs.dump(self.integration_bridge),
                                       metadataid, tunnel_key_hex)
        self.assertIsNotNone(r)
        vm.close()
        network.close()
