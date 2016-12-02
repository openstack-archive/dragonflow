# Copyright (c) 2016 OpenStack Foundation.
# All Rights Reserved.
#
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

import mock
from oslo_config import cfg

from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import models as db_models
from dragonflow.tests import base as tests_base


class DFAppTestBase(tests_base.BaseTestCase):
    apps_list = ""

    def setUp(self, enable_selective_topo_dist=False):
        cfg.CONF.set_override('apps_list', self.apps_list, group='df')
        super(DFAppTestBase, self).setUp()
        mock.patch('ryu.base.app_manager.AppManager.get_instance').start()
        self.controller = df_local_controller.DfLocalController('fake_host')
        self.nb_api = self.controller.nb_api = mock.MagicMock()
        self.vswitch_api = self.controller.vswitch_api = mock.MagicMock()
        kwargs = dict(
            nb_api=self.controller.nb_api,
            vswitch_api=self.controller.vswitch_api,
            db_store=self.controller.db_store
        )
        self.controller.open_flow_app = ryu_base_app.RyuDFAdapter(**kwargs)
        self.open_flow_app = self.controller.open_flow_app
        self.datapath = self.open_flow_app._datapath = mock.Mock()
        self.open_flow_app.load(self.controller.open_flow_app, **kwargs)
        self.topology = self.controller.topology = topology.Topology(
            self.controller, enable_selective_topo_dist)

        # Add basic network topology
        self.controller.logical_switch_updated(fake_logic_switch1)
        self.controller.logical_switch_updated(fake_external_switch1)
        self.controller.router_updated(fake_logic_router1)

        self.arp_responder = mock.patch(
            'dragonflow.controller.common.arp_responder.ArpResponder').start()
        mock.patch(
            'dragonflow.controller.df_base_app.DFlowApp.mod_flow').start()
        mock.patch('dragonflow.controller.df_base_app.DFlowApp.'
                   'add_flow_go_to_table').start()

fake_logic_router1 = db_models.LogicalRouter("{}")
fake_logic_router1.inner_obj = {
    "description": "",
    "name": "router1",
    "admin_state_up": True,
    "distributed": False,
    "gateway": {"network_id": "fake_external_switch1",
                "enable_snat": True,
                "port_id": "fake_gateway_port_id",
                "external_fixed_ips": [
                    {"subnet_id": "fake_external_subnet1",
                     "ip_address": "172.24.4.11"}]},
    "topic": "fake_tenant1",
    "version": 10,
    "routes": [],
    "id": "fake_router_id",
    "ports": [{"network": "10.0.0.1/24",
               "lswitch": "fake_switch1",
               "topic": "fake_tenant1",
               "mac": "fa:16:3e:50:96:f4",
               "unique_key": 14,
               "lrouter": "fake_router_id",
               "id": "fake_router_port1"}]}


fake_logic_switch1 = db_models.LogicalSwitch("{}")
fake_logic_switch1.inner_obj = {
    "subnets": [{"dhcp_ip": "10.0.0.2",
                 "name": "private-subnet",
                 "enable_dhcp": True,
                 "lswitch": "fake_switch1",
                 "dns_nameservers": [],
                 "topic": "fake_tenant1",
                 "gateway_ip": "10.0.0.1",
                 "host_routes": [],
                 "cidr": "10.0.0.0/24",
                 "id": "fake_subnet1"}],
    "name": "private",
    "router_external": False,
    "segmentation_id": 41,
    "mtu": 1450,
    "topic": "fake_tenant1",
    "version": 2,
    "network_type": "vxlan",
    "id": "fake_switch1",
    "unique_key": 1}


fake_external_switch1 = db_models.LogicalSwitch("{}")
fake_external_switch1.inner_obj = {
    "subnets": [{"name": "public-subnet",
                 "enable_dhcp": False,
                 "lswitch": "fake_external_switch1",
                 "dns_nameservers": [],
                 "topic": "fake_tenant1",
                 "gateway_ip": "172.24.4.1",
                 "host_routes": [],
                 "cidr": "172.24.4.0/24",
                 "id": "fake_external_subnet1"}],
    "name": "public",
    "router_external": True,
    "segmentation_id": 69,
    "mtu": 1450,
    "topic": "fake_tenant1",
    "version": 2,
    "network_type": "vxlan",
    "id": "fake_external_switch1"}


fake_local_port1 = db_models.LogicalPort("{}")
fake_local_port1.inner_obj = {
    'subnets': ['fake_subnet1'],
    'binding_profile': {},
    'macs': ['fa:16:3e:8c:2e:b3'],
    'name': '',
    'allowed_address_pairs': [],
    'lswitch': 'fake_switch1',
    'enabled': True,
    'topic': 'fake_tenant1',
    'ips': ['10.0.0.6'],
    'device_owner': 'compute:None',
    'chassis': 'fake_host',
    'version': 2,
    'unique_key': 2,
    'port_security_enabled': True,
    'binding_vnic_type': 'normal',
    'id': 'fake_port1',
    'security_groups': ['fake_security_group_id1'],
    'device_id': 'fake_device_id'}
fake_local_port1.external_dict = {'is_local': True,
                                  'segmentation_id': 41,
                                  'ofport': 2,
                                  'network_type': 'vxlan',
                                  'local_network_id': 1}


fake_ovs_port1 = mock.Mock(name='fake_ovs_port1')
fake_ovs_port1.get_id.return_value = 'fake_ovs_port1'
fake_ovs_port1.get_ofport.return_value = 2
fake_ovs_port1.get_name.return_value = 'tap-fake_port1'
fake_ovs_port1.get_admin_state.return_value = True
fake_ovs_port1.get_type.return_value = db_models.OvsPort.TYPE_VM
fake_ovs_port1.get_iface_id.return_value = 'fake_port1'
fake_ovs_port1.get_peer.return_value = ''
fake_ovs_port1.get_attached_mac.return_value = 'fa:16:3e:8c:2e:b3'
fake_ovs_port1.get_remote_ip.return_value = ''
fake_ovs_port1.get_tunnel_type.return_value = 'vxlan'


fake_local_port2 = db_models.LogicalPort("{}")
fake_local_port2.inner_obj = {
    'subnets': ['fake_subnet1'],
    'binding_profile': {},
    'macs': ['fa:16:3e:8c:2e:b4'],
    'name': '',
    'allowed_address_pairs': [],
    'lswitch': 'fake_switch1',
    'enabled': True,
    'topic': 'fake_tenant1',
    'ips': ['10.0.0.7'],
    'device_owner': 'compute:None',
    'chassis': 'fake_host',
    'version': 2,
    'tunnel_key': 3,
    'port_security_enabled': True,
    'binding_vnic_type': 'normal',
    'id': 'fake_port2',
    'security_groups': ['fake_security_group_id1'],
    'device_id': 'fake_device_id'}
fake_local_port2.external_dict = {'is_local': True,
                                  'segmentation_id': 41,
                                  'ofport': 3,
                                  'network_type': 'vxlan',
                                  'local_network_id': 1}


fake_ovs_port2 = mock.Mock(name='fake_ovs_port2')
fake_ovs_port2.get_id.return_value = 'fake_ovs_port2'
fake_ovs_port2.get_ofport.return_value = 3
fake_ovs_port2.get_name.return_value = 'tap-fake_port2'
fake_ovs_port2.get_admin_state.return_value = True
fake_ovs_port2.get_type.return_value = db_models.OvsPort.TYPE_VM
fake_ovs_port2.get_iface_id.return_value = 'fake_port2'
fake_ovs_port2.get_peer.return_value = ''
fake_ovs_port2.get_attached_mac.return_value = 'fa:16:3e:8c:2e:b4'
fake_ovs_port2.get_remote_ip.return_value = ''
fake_ovs_port2.get_tunnel_type.return_value = 'vxlan'


fake_remote_port1 = db_models.LogicalPort("{}")
fake_remote_port1.inner_obj = {
    'subnets': ['fake_subnet1'],
    'binding_profile': {},
    'macs': ['fa:16:3e:8c:2e:af'],
    'name': '',
    'allowed_address_pairs': [],
    'lswitch': 'fake_switch1',
    'enabled': True,
    'topic': 'fake_tenant1',
    'ips': ['10.0.0.8'],
    'device_owner': 'compute:None',
    'chassis': 'fake_host2',
    'version': 2,
    'unique_key': 5,
    'port_security_enabled': True,
    'binding_vnic_type': 'normal',
    'id': 'fake_remote_port',
    'security_groups': ['fake_security_group_id1'],
    'device_id': 'fake_device_id'}
fake_remote_port1.external_dict = {'is_local': False,
                                  'segmentation_id': 41,
                                  'ofport': 1,
                                  'network_type': 'vxlan',
                                  'local_network_id': 1}


fake_floatingip1 = db_models.Floatingip("{}")
fake_floatingip1.inner_obj = {
    'router_id': 'fake_router_id',
    'status': 'DOWN',
    'name': 'no_fip_name',
    'floating_port_id': 'fake_floatingip_port_id',
    'floating_mac_address': 'fa:16:3e:76:a2:84',
    'floating_network_id': 'fake_external_switch1',
    'topic': 'fake_tenant1',
    'fixed_ip_address': '10.0.0.6',
    'floating_ip_address': '172.24.4.2',
    'version': 7,
    'external_cidr': '172.24.4.0/24',
    'port_id': 'fake_port1',
    'id': 'fake_floatingip_id1',
    'external_gateway_ip': u'172.24.4.1'}


fake_security_group = db_models.SecurityGroup("{}")
fake_security_group.inner_obj = {
    "description": "",
    "name": "fake_security_group",
    "topic": "fake_tenant1",
    "version": 5,
    "id": "fake_security_group_id1",
    "rules": [{"direction": "egress",
               "security_group_id": "fake_security_group_id1",
               "ethertype": "IPv4",
               "topic": "fake_tenant1",
               "port_range_max": 53,
               "port_range_min": 53,
               "protocol": "udp",
               "remote_group_id": None,
               "remote_ip_prefix": "192.168.180.0/28",
               "id": "fake_security_group_rule_1"},
              {"direction": "ingress",
               "security_group_id": "fake_security_group_id1",
               "ethertype": "IPv4",
               "topic": "fake_tenant1",
               "port_range_max": None,
               "port_range_min": None,
               "protocol": None,
               "remote_group_id": "fake_security_group_id1",
               "remote_ip_prefix": None,
               "id": "fake_security_group_rule_2"}]}
