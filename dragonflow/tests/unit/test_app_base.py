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
from neutron_lib import constants as n_const
from oslo_config import cfg

from dragonflow.common import constants
from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_store2
from dragonflow.db import model_framework
from dragonflow.db import model_proxy
from dragonflow.db import models as db_models
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.db.models import ovs
from dragonflow.db.models import secgroups
from dragonflow.tests import base as tests_base


class DFAppTestBase(tests_base.BaseTestCase):
    apps_list = ""

    def setUp(self, enable_selective_topo_dist=False):
        cfg.CONF.set_override('apps_list', self.apps_list, group='df')
        super(DFAppTestBase, self).setUp()
        mock.patch('ryu.base.app_manager.AppManager.get_instance').start()
        mock.patch('dragonflow.db.api_nb.NbApi.get_instance').start()
        mod_flow = mock.patch(
            'dragonflow.controller.df_base_app.DFlowApp.mod_flow').start()
        add_flow_go_to_table_mock_patch = mock.patch(
            'dragonflow.controller.df_base_app.DFlowApp.add_flow_go_to_table')
        add_flow_go_to_table = add_flow_go_to_table_mock_patch.start()
        execute = mock.patch('neutron.agent.common.utils.execute').start()

        # CLear old objects from cache
        db_store2._instance = None

        nb_api = api_nb.NbApi.get_instance(False)
        self.controller = df_local_controller.DfLocalController('fake_host',
                                                                nb_api)
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
        self.controller.update(fake_logic_switch1)
        self.controller.update(fake_external_switch1)
        self.controller.update(fake_logic_router1)
        self.controller.db_store2.update(fake_chassis1)
        self.controller.db_store2.update(fake_chassis2)

        mod_flow.reset_mock()
        add_flow_go_to_table.reset_mock()
        execute.reset_mock()

    def tearDown(self):
        for model in model_framework.iter_models(False):
            model.clear_registered_callbacks()
        super(DFAppTestBase, self).tearDown()


fake_logical_router_ports = [l3.LogicalRouterPort(network="10.0.0.1/24",
                                                  lswitch="fake_switch1",
                                                  topic="fake_tenant1",
                                                  mac="fa:16:3e:50:96:f4",
                                                  unique_key=14,
                                                  id="fake_router_port1")]


fake_logic_router1 = l3.LogicalRouter(
    name="router1",
    topic="fake_tenant1",
    version=10,
    routes=[],
    id="fake_router_id",
    unique_key=1,
    ports=fake_logical_router_ports)


fake_lswitch_default_subnets = [l2.Subnet(dhcp_ip="10.0.0.2",
                                          name="private-subnet",
                                          enable_dhcp=True,
                                          topic="fake_tenant1",
                                          gateway_ip="10.0.0.1",
                                          cidr="10.0.0.0/24",
                                          id="fake_subnet1")]


fake_logic_switch1 = l2.LogicalSwitch(
        subnets=fake_lswitch_default_subnets,
        unique_key=1,
        name='private',
        is_external=False,
        segmentation_id=41,
        mtu=1450,
        topic='fake_tenant1',
        id='fake_switch1',
        version=5)


external_switch1_subnets = [l2.Subnet(name="public-subnet",
                                      enable_dhcp=False,
                                      topic="fake_tenant1",
                                      gateway_ip="172.24.4.1",
                                      cidr="172.24.4.0/24",
                                      id="fake_external_subnet1")]


fake_external_switch1 = l2.LogicalSwitch(
        subnets=external_switch1_subnets,
        unique_key=2,
        name='public',
        is_external=True,
        segmentation_id=69,
        mtu=1450,
        topic='fake_tenant1',
        id='fake_external_switch1')


def make_fake_port(id=None,
                   subnets=None,
                   is_local=None,
                   macs=('00:00:00:00:00:00',),
                   ips=('0.0.0.0',),
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
    fake_port = l2.LogicalPort(
        id="%s_%s%s" % (network_type, name, ofport) if not id else id,
        topic=topic,
        name=name,
        unique_key=unique_key,
        version=version,
        ips=ips,
        subnets=subnets,
        macs=macs,
        chassis=chassis,
        lswitch=lswitch,
        security_groups=security_groups,
        allowed_address_pairs=[],
        port_security_enabled=port_security_enabled,
        device_owner=device_owner,
        device_id=device_id,
        # binding_vnic_type=binding_vnic_type,
        extra_dhcp_options=extra_dhcp_opts,
    )
    fake_port.is_local = is_local
    fake_port.segmentation_id = segmentation_id
    fake_port.ofport = ofport
    fake_port.network_type = network_type
    fake_port.local_network_id = local_network_id
    fake_port.tunnel_key = tunnel_key
    return fake_port


def make_fake_local_port(**kargs):
    kargs['is_local'] = True
    return make_fake_port(**kargs)


fake_local_port1_dhcp_opts = [
    l2.DHCPOption(tag=3, value='10.0.0.1'),
    l2.DHCPOption(tag=121, value='0.0.0.0/0,10.0.0.1'),
]


fake_local_port1 = make_fake_local_port(
    macs=['fa:16:3e:8c:2e:b3'],
    ips=['10.0.0.6', '2222:2222::3'],
    network_type='vxlan',
    subnets=[model_proxy.create_reference(l2.Subnet, 'fake_subnet1')],
    id='fake_port1',
    extra_dhcp_opts=fake_local_port1_dhcp_opts)


fake_ovs_port1 = ovs.OvsPort(
    id='fake_ovs_port1',
    ofport=2,
    name='tap-fake_port1',
    admin_state='up',
    type=constants.OVS_VM_INTERFACE,
    iface_id='fake_port1',
    attached_mac='fa:16:3e:8c:2e:b3',
    tunnel_type='vxlan',
)


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


fake_ovs_port2 = ovs.OvsPort(
    id='fake_ovs_port2',
    ofport=3,
    name='tap-fake_port2',
    admin_state='up',
    type=constants.OVS_VM_INTERFACE,
    iface_id='fake_port2',
    attached_mac='fa:16:3e:8c:2e:b4',
    tunnel_type='vxlan',
)


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


fake_chassis1 = core.Chassis(
    id='fake_host',
    ip='172.24.4.50',
    tunnel_types=('vxlan',),
)


fake_chassis2 = core.Chassis(
    id='fake_host2',
    ip='172.24.4.51',
    tunnel_types=('vxlan',),
)


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


fake_security_group = secgroups.SecurityGroup(
    name="fake_security_group",
    topic="fake_tenant1",
    version=5,
    unique_key=1,
    id="fake_security_group_id1",
    rules=[secgroups.SecurityGroupRule(
            direction="egress",
            security_group_id="fake_security_group_id1",
            ethertype=n_const.IPv4,
            topic="fake_tenant1",
            port_range_max=53,
            port_range_min=53,
            protocol="udp",
            remote_group_id=None,
            remote_ip_prefix="192.168.180.0/28",
            id="fake_security_group_rule_1"),
           secgroups.SecurityGroupRule(
            direction="ingress",
            security_group_id="fake_security_group_id1",
            ethertype="IPv4",
            topic="fake_tenant1",
            port_range_max=None,
            port_range_min=None,
            protocol=None,
            remote_group_id="fake_security_group_id1",
            remote_ip_prefix=None,
            id="fake_security_group_rule_2"),
           secgroups.SecurityGroupRule(
            direction="egress",
            security_group_id="fake_security_group_id1",
            ethertype=n_const.IPv6,
            topic="fake_tenant1",
            port_range_max=53,
            port_range_min=53,
            protocol="udp",
            remote_group_id=None,
            remote_ip_prefix="1111::/64",
            id="fake_security_group_rule_3"),
           secgroups.SecurityGroupRule(
            direction="ingress",
            security_group_id="fake_security_group_id1",
            ethertype=n_const.IPv6,
            topic="fake_tenant1",
            port_range_max=None,
            port_range_min=None,
            protocol=None,
            remote_group_id="fake_security_group_id1",
            remote_ip_prefix=None,
            id="fake_security_group_rule_4")])
