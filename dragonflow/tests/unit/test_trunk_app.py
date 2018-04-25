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
import netaddr
import ryu.lib.packet

from dragonflow.controller.common import constants
from dragonflow.controller import datapath_layout
from dragonflow.controller import port_locator
from dragonflow.db import db_store
from dragonflow.db.models import l2
from dragonflow.db.models import trunk
from dragonflow.tests.unit import test_app_base


class SettingMock(object):
    def __init__(self, *args, **kwargs):
        self._dict = kwargs
        for idx, arg in enumerate(args):
            self._dict[idx] = arg

    def __getattr__(self, attrname):
        if attrname.startswith('set_'):
            def setter(x):
                self._dict[attrname[4:]] = x
            return setter

    def __repr__(self):
        return 'SettingMock(%r)' % self._dict

    def __eq__(self, other):
        if isinstance(other, SettingMock):
            return self._dict == other._dict
        if isinstance(other, dict):
            return self._dict == other
        return super(SettingMock, self) == other


def _create_2nd_lswitch():
    lswitch = l2.LogicalSwitch(id='lswitch2',
                               unique_key=17,
                               segmentation_id=17,
                               topic='fake_tenant1')
    return lswitch


def _create_2nd_subnet():
    return l2.Subnet(id='subnet2',
                     enable_dhcp=False,
                     cidr='192.168.18.0/24',
                     topic='fake_tenant1')


def _create_child_port():
    return l2.LogicalPort(id='lport2',
                          ips=['192.168.18.3'],
                          subnets=['subnet2'],
                          macs=['fa:16:3e:00:00:01'],
                          enabled=True,
                          lswitch='lswitch2',
                          topic='fake_tenant1',
                          unique_key=33,
                          version=2)


def _create_segmentation():
    return trunk.ChildPortSegmentation(id='cps1',
                                       topic='fake_tenant1',
                                       parent='fake_port2',
                                       port='lport2',
                                       segmentation_type='vlan',
                                       segmentation_id=7)


class TestTrunkApp(test_app_base.DFAppTestBase):
    apps_list = ["trunk"]

    def setUp(self):
        super(TestTrunkApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['trunk']
        self.mock_mod_flow = self.app.mod_flow
        self.db_store = db_store.get_instance()
        self.app.ofproto.OFPVID_PRESENT = 0x1000
        self.db_store.update(test_app_base.fake_local_port2)

    def get_layout(self):
        edges = ()
        vertices = (
            datapath_layout.Vertex(
                name='classifier',
                type='classifier',
                params=None,
            ),
            # Uncomment once trunk port gets converted
            #datapath_layout.Vertex(
            #    name='trunk',
            #    type='trunk',
            #    params=None,
            #),
        )
        return datapath_layout.Layout(vertices, edges)

    def test_create_child_segmentation(self):
        lswitch2 = _create_2nd_lswitch()
        self.controller.update(lswitch2)
        subnet2 = _create_2nd_subnet()
        self.controller.update(subnet2)

        lport = _create_child_port()
        self.controller.update(lport)

        segmentation = _create_segmentation()
        self.controller.update(segmentation)

        classification_flow = mock.call(
            table_id=self.dfdp.apps['classifier'].states.classification,
            priority=constants.PRIORITY_HIGH,
            match=mock.ANY,
            actions=mock.ANY,
        )
        dispatch_flow = mock.call(
            table_id=self.dfdp.apps['classifier'].states.dispatch,
            priority=constants.PRIORITY_HIGH,
            match=mock.ANY,
            actions=mock.ANY,
        )
        self.mock_mod_flow.assert_has_calls((classification_flow,
                                             dispatch_flow))

    def test_delete_child_segmentation(self):
        lswitch2 = _create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = _create_child_port()
        self.db_store.update(lport)
        segmentation = _create_segmentation()
        self.db_store.update(segmentation)
        port_locator.set_port_binding(lport, object())

        self.controller.delete_by_id(type(segmentation), segmentation.id)

        classification_flow = mock.call(
                table_id=self.dfdp.apps['classifier'].states.classification,
                priority=constants.PRIORITY_HIGH,
                match=mock.ANY,
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )
        dispatch_flow = mock.call(
            table_id=self.dfdp.apps['classifier'].states.dispatch,
            priority=constants.PRIORITY_MEDIUM,
            match=mock.ANY,
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )
        self.mock_mod_flow.assert_has_calls((classification_flow,
                                             dispatch_flow))


class _TestTrunkSegmentationTypes(object):
    apps_list = ["trunk"]

    def setUp(self):
        super(_TestTrunkSegmentationTypes, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['trunk']
        self.mock_mod_flow = self.app.mod_flow
        self.db_store = db_store.get_instance()
        self.app.ofproto.OFPVID_PRESENT = 0x1000
        self.db_store.update(test_app_base.fake_local_port2)

    def get_layout(self):
        edges = ()
        vertices = (
            datapath_layout.Vertex(
                name='classifier',
                type='classifier',
                params=None,
            ),
            # Uncomment once trunk port gets converted
            #datapath_layout.Vertex(
            #    name='trunk',
            #    type='trunk',
            #    params=None,
            #),
        )
        return datapath_layout.Layout(vertices, edges)

    def test_installed_flows(self):
        lswitch2 = _create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = _create_child_port()
        self.db_store.update(lport)
        segmentation = self.create_segmentation()
        self.db_store.update(segmentation)

        self.app.mod_flow.reset_mock()
        self.app.parser.OFPMatch.side_effect = SettingMock
        self.app.parser.OFPActionSetField.side_effect = SettingMock
        self.app._install_local_cps(segmentation)
        expected_matches = self.get_expected_matches()
        expected_actions = self.get_expected_actions()
        calls = self.app.mod_flow.call_args_list
        for expected_match, expected_action, call in zip(expected_matches,
                                                         expected_actions,
                                                         calls):
            args, kwargs = call
            match = kwargs['match']
            match_dict = match._dict
            self.assertEqual(expected_match, match_dict)
            action = kwargs['actions']
            self.assertEqual(expected_action, action)
        self.assertEqual(len(expected_matches), len(calls))
        self.assertEqual(len(expected_actions), len(calls))


class TestTrunkSegmentationTypesVLAN(_TestTrunkSegmentationTypes,
                                     test_app_base.DFAppTestBase):
    def create_segmentation(self):
        return _create_segmentation()

    def get_expected_matches(self):
        return [
            {'reg6': test_app_base.fake_local_port2.unique_key,
             'vlan_vid': 0x1007},
            {'reg7': 33}
        ]

    def get_expected_actions(self):
        return [
            [
                SettingMock(reg6=33),
                SettingMock(metadata=17),
                self.app.parser.OFPActionPopVlan(),
                self.app.parser.NXActionResubmit(),
            ], [
                self.app.parser.OFPActionPushVlan(),
                SettingMock(vlan_vid=0x1007),
                SettingMock(reg7=test_app_base.fake_local_port2.unique_key),
                self.app.parser.NXActionResubmit(),
            ]
        ]


class TestTrunkSegmentationTypesMACVLAN(_TestTrunkSegmentationTypes,
                                        test_app_base.DFAppTestBase):
    def create_segmentation(self):
        segmentation = _create_segmentation()
        segmentation.segmentation_type = trunk.TYPE_MACVLAN
        return segmentation

    def get_expected_matches(self):
        return [
            {
                'reg6': test_app_base.fake_local_port2.unique_key,
                'eth_src': netaddr.EUI('fa:16:3e:00:00:01'),
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_IP,
                'ipv4_src': netaddr.IPAddress('192.168.18.3'),
            }, {
                'reg7': 33,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_IP,
            }, {
                'reg6': test_app_base.fake_local_port2.unique_key,
                'eth_src': netaddr.EUI('fa:16:3e:00:00:01'),
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_ARP,
                'arp_sha': netaddr.EUI('fa:16:3e:00:00:01'),
                'arp_spa': netaddr.IPAddress('192.168.18.3'),
            }, {
                'reg7': 33,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_ARP,
            }
        ]

    def get_expected_actions(self):
        return [
            [
                SettingMock(reg6=33),
                SettingMock(metadata=17),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(reg7=test_app_base.fake_local_port2.unique_key),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(reg6=33),
                SettingMock(metadata=17),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(reg7=test_app_base.fake_local_port2.unique_key),
                self.app.parser.NXActionResubmit(),
            ]
        ]


class TestTrunkSegmentationTypesIPVLAN(_TestTrunkSegmentationTypes,
                                       test_app_base.DFAppTestBase):
    def create_segmentation(self):
        segmentation = _create_segmentation()
        segmentation.segmentation_type = trunk.TYPE_IPVLAN
        return segmentation

    def get_expected_matches(self):
        return [
            {
                'reg6': test_app_base.fake_local_port2.unique_key,
                'eth_src': test_app_base.fake_local_port2.mac,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_IP,
                'ipv4_src': netaddr.IPAddress('192.168.18.3'),
            }, {
                'reg7': 33,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_IP,
            }, {
                'reg6': test_app_base.fake_local_port2.unique_key,
                'eth_src': test_app_base.fake_local_port2.mac,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_ARP,
                'arp_sha': test_app_base.fake_local_port2.mac,
                'arp_spa': netaddr.IPAddress('192.168.18.3'),
            }, {
                'reg7': 33,
                'eth_type': ryu.lib.packet.ether_types.ETH_TYPE_ARP,
            }
        ]

    def get_expected_actions(self):
        return [
            [
                SettingMock(reg6=33),
                SettingMock(metadata=17),
                SettingMock(eth_src=netaddr.EUI('fa:16:3e:00:00:01')),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(eth_dst=test_app_base.fake_local_port2.mac),
                SettingMock(reg7=test_app_base.fake_local_port2.unique_key),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(reg6=33),
                SettingMock(metadata=17),
                SettingMock(eth_src=netaddr.EUI('fa:16:3e:00:00:01')),
                SettingMock(arp_sha=netaddr.EUI('fa:16:3e:00:00:01')),
                self.app.parser.NXActionResubmit(),
            ], [
                SettingMock(eth_dst=test_app_base.fake_local_port2.mac),
                SettingMock(arp_tha=test_app_base.fake_local_port2.mac),
                SettingMock(reg7=test_app_base.fake_local_port2.unique_key),
                self.app.parser.NXActionResubmit(),
            ]
        ]
