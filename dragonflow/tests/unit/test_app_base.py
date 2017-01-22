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
        self.controller.update_lswitch(fake_logic_switch1)
        self.controller.update_lswitch(fake_external_switch1)
        self.controller.update_lrouter(fake_logic_router1)
        self.controller.db_store.update_chassis('fake_host', fake_chassis1)
        self.controller.db_store.update_chassis('fake_host2', fake_chassis2)

        self.arp_responder = mock.patch(
            'dragonflow.controller.common.arp_responder.ArpResponder').start()
        mock.patch(
            'dragonflow.controller.df_base_app.DFlowApp.mod_flow').start()
        mock.patch('dragonflow.controller.df_base_app.DFlowApp.'
                   'add_flow_go_to_table').start()
        mock.patch('neutron.agent.common.utils.execute').start()

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

fake_lswitch_default_subnets = [{"dhcp_ip": "10.0.0.2",
                 "name": "private-subnet",
                 "enable_dhcp": True,
                 "lswitch": "fake_switch1",
                 "dns_nameservers": [],
                 "topic": "fake_tenant1",
                 "gateway_ip": "10.0.0.1",
                 "host_routes": [],
                 "cidr": "10.0.0.0/24",
                 "id": "fake_subnet1"}]


def make_fake_logic_switch(
        unique_key,
        name,
        router_external,
        segmentation_id,
        mtu,
        topic,
        id,
        subnets=None,
        network_type='vxlan',
        version=2,
        **kwargs):
    fake_switch = db_models.LogicalSwitch("{}")
    fake_switch.inner_obj = {
            "subnets": subnets,
            "name": name,
            "router_external": router_external,
            "segmentation_id": segmentation_id,
            "mtu": mtu,
            "topic": topic,
            "version": version,
            "network_type": network_type,
            "id": id,
            "unique_key": unique_key}
    fake_switch.inner_obj.update(kwargs)
    return fake_switch

fake_logic_switch1 = make_fake_logic_switch(
        subnets=fake_lswitch_default_subnets,
        unique_key=1,
        name='private',
        router_external=False,
        segmentation_id=41,
        mtu=1450,
        topic='fake_tenant1',
        id='fake_switch1')

external_switch1_subnets = [{"name": "public-subnet",
                 "enable_dhcp": False,
                 "lswitch": "fake_external_switch1",
                 "dns_nameservers": [],
                 "topic": "fake_tenant1",
                 "gateway_ip": "172.24.4.1",
                 "host_routes": [],
                 "cidr": "172.24.4.0/24",
                 "id": "fake_external_subnet1"}]


fake_external_switch1 = make_fake_logic_switch(
        subnets=external_switch1_subnets,
        unique_key=2,
        name='public',
        router_external=True,
        segmentation_id=69,
        mtu=1450,
        topic='fake_tenant1',
        id='fake_external_switch1')


def make_fake_port(id=None,
                   subnets=None,
                   is_local=None,
                   macs=('00:00:00:00:00:00'),
                   ips=('0.0.0.0.0'),
                   name='fake_local_port',
                   lswitch='fake_switch1',
                   enabled=True,
                   topic='fake_tenant1',
                   device_owner='compute:None',
                   chassis='fake_host',
                   version=2,
                   tunnel_key=None,
                   unique_key=2,
                   port_security_enabled=True,
                   network_type='flat',
                   binding_vnic_type='normal',
                   security_groups=['fake_security_group_id1'],
                   device_id='fake_device_id',
                   segmentation_id=42,
                   ofport=1,
                   local_network_id=11,
                   extra_dhcp_opts=None):
    fake_port = db_models.LogicalPort("{}")
    fake_port.inner_obj = {
        'subnets': subnets,
        'binding_profile': {},
        'macs': macs,
        'name': name,
        'allowed_address_pairs': [],
        'lswitch': lswitch,
        'enabled': True,
        'topic': topic,
        'ips': ips,
        'device_owner': device_owner,
        'tunnel_key': tunnel_key,
        'chassis': chassis,
        'version': version,
        'unique_key': unique_key,
        'port_security_enabled': port_security_enabled,
        'binding_vnic_type': binding_vnic_type,
        'id': "%s_%s%s" % (network_type, name, ofport) if not id else id,
        'security_groups': security_groups,
        'device_id': device_id,
        'extra_dhcp_opts': extra_dhcp_opts}
    fake_port.external_dict = {
        'is_local': is_local,
        'segmentation_id': segmentation_id,
        'ofport': ofport,
        'network_type': network_type,
        'local_network_id': local_network_id}
    return fake_port


def make_fake_local_port(**kargs):
    kargs['is_local'] = True
    return make_fake_port(**kargs)


fake_local_port1_dhcp_opts = [{
    'opt_value': "10.0.0.1",
    'opt_name': "3",
    'ip_version': 4}, {
    'opt_value': "0.0.0.0/0,10.0.0.1",
    'opt_name': "121",
    'ip_version': 4}]


fake_local_port1 = make_fake_local_port(
    macs=['fa:16:3e:8c:2e:b3'],
    ips=['10.0.0.6'],
    network_type='vxlan',
    subnets=['fake_subnet1'],
    id='fake_port1',
    extra_dhcp_opts=fake_local_port1_dhcp_opts)


fake_ovs_port1 = mock.Mock(name='fake_ovs_port1')
fake_ovs_port1.get_id.return_value = 'fake_ovs_port1'
fake_ovs_port1.get_ofport.return_value = 2
fake_ovs_port1.get_name.return_value = 'tap-fake_port1'
fake_ovs_port1.get_admin_state.return_value = True
fake_ovs_port1.get_type.return_value = db_models.OvsPort.TYPE_VM
fake_ovs_port1.get_iface_id.return_value = 'fake_port1'
fake_ovs_port1.get_peer.return_value = ''
fake_ovs_port1.get_attached_mac.return_value = 'fa:16:3e:8c:2e:b3'
fake_ovs_port1.get_tunnel_type.return_value = 'vxlan'


fake_local_port2 = make_fake_local_port(
    macs=['fa:16:3e:8c:2e:b4'],
    ips=['10.0.0.7'],
    tunnel_key=3,
    id='fake_port2',
    segmentation_id=41,
    ofport=3,
    network_type='vxlan',
    subnets=['fake_subnet1'],
    local_network_id=1)


fake_ovs_port2 = mock.Mock(name='fake_ovs_port2')
fake_ovs_port2.get_id.return_value = 'fake_ovs_port2'
fake_ovs_port2.get_ofport.return_value = 3
fake_ovs_port2.get_name.return_value = 'tap-fake_port2'
fake_ovs_port2.get_admin_state.return_value = True
fake_ovs_port2.get_type.return_value = db_models.OvsPort.TYPE_VM
fake_ovs_port2.get_iface_id.return_value = 'fake_port2'
fake_ovs_port2.get_peer.return_value = ''
fake_ovs_port2.get_attached_mac.return_value = 'fa:16:3e:8c:2e:b4'
fake_ovs_port2.get_tunnel_type.return_value = 'vxlan'


def make_fake_remote_port(**kargs):
    kargs['is_local'] = False
    return make_fake_port(**kargs)


fake_remote_port1 = make_fake_remote_port(
    id='fake_remote_port',
    macs=['fa:16:3e:8c:2e:af'],
    name='fake_remote_port',
    ips=['10.0.0.8'],
    chassis='fake_host2',
    unique_key=5,
    segmentation_id=41,
    ofport=1,
    network_type='vxlan',
    subnets=['fake_subnet1'],
    local_network_id=1)


fake_chassis1 = db_models.Chassis("{}")
fake_chassis1.inner_obj = {
    'id': 'fake_host',
    'ip': '172.24.4.50'
}


fake_chassis2 = db_models.Chassis("{}")
fake_chassis2.inner_obj = {
    'id': 'fake_host2',
    'ip': '172.24.4.51'
}


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
    "unique_key": 1,
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
