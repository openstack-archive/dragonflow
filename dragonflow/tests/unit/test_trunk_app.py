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

from dragonflow.controller.common import constants
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

    def __eq__(self, other):
        if isinstance(other, SettingMock):
            return self._dict == other._dict
        return super(SettingMock, self) == other


class TestTrunkApp(test_app_base.DFAppTestBase):
    apps_list = ["trunk"]

    def setUp(self):
        super(TestTrunkApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['trunk']
        self.mock_mod_flow = self.app.mod_flow
        self.db_store = db_store.get_instance()
        self.app.ofproto.OFPVID_PRESENT = 0x1000
        self.db_store.update(test_app_base.fake_local_port2)

    def _create_2nd_lswitch(self):
        lswitch = l2.LogicalSwitch(id='lswitch2',
                                   unique_key=17,
                                   segmentation_id=17,
                                   topic='fake_tenant1')
        subnet = self._create_2nd_subnet()
        lswitch.add_subnet(subnet)
        return lswitch

    def _create_2nd_subnet(self):
        return l2.Subnet(id='subnet2',
                         enable_dhcp=False,
                         cidr='192.168.18.0/24',
                         topic='fake_tenant1')

    def _create_child_port(self):
        return l2.LogicalPort(id='lport2',
                              ips=['192.168.18.3'],
                              subnets=['subnet2'],
                              macs=['fa:16:3e:00:00:01'],
                              enabled=True,
                              lswitch='lswitch2',
                              topic='fake_tenant1',
                              unique_key=33,
                              version=2)

    def _create_segmentation(self):
        return trunk.ChildPortSegmentation(id='cps1',
                                           topic='fake_tenant1',
                                           parent='fake_port2',
                                           port='lport2',
                                           segmentation_type='vlan',
                                           segmentation_id=7)

    def test_create_child_segmentation(self):
        lswitch2 = self._create_2nd_lswitch()
        self.controller.update(lswitch2)

        lport = self._create_child_port()
        self.controller.update(lport)

        segmentation = self._create_segmentation()
        self.controller.update(segmentation)

        classification_flow = mock.call(
            table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=mock.ANY,
            actions=mock.ANY,
        )
        dispatch_flow = mock.call(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=mock.ANY,
            actions=mock.ANY,
        )
        self.mock_mod_flow.assert_has_calls((classification_flow,
                                             dispatch_flow))

    def test_delete_child_segmentation(self):
        lswitch2 = self._create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = self._create_child_port()
        self.db_store.update(lport)
        segmentation = self._create_segmentation()
        self.db_store.update(segmentation)
        port_locator.set_port_binding(lport, object())

        self.controller.delete_by_id(type(segmentation), segmentation.id)

        classification_flow = mock.call(
                table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=mock.ANY,
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )
        dispatch_flow = mock.call(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=mock.ANY,
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )
        self.mock_mod_flow.assert_has_calls((classification_flow,
                                             dispatch_flow))

    def test__get_classification_match(self):
        lswitch2 = self._create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = self._create_child_port()
        self.db_store.update(lport)
        segmentation = self._create_segmentation()
        self.db_store.update(segmentation)
        self.app.parser.OFPMatch.side_effect = SettingMock

        match = self.app._get_classification_match(segmentation)
        match_dict = match._dict
        self.assertEqual({'reg6': test_app_base.fake_local_port2.unique_key,
                          'vlan_vid': 0x1007},
                         match_dict)

    def test__get_classification_actions(self):
        lswitch2 = self._create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = self._create_child_port()
        self.db_store.update(lport)
        segmentation = self._create_segmentation()
        self.db_store.update(segmentation)
        self.app.parser.OFPActionSetField.side_effect = SettingMock
        actions = self.app._get_classification_actions(segmentation)
        self.assertEqual(4, len(actions))
        self.assertEqual({'reg6': 33}, actions[0]._dict)
        self.assertEqual({'metadata': 17}, actions[1]._dict)
        self.assertEqual(self.app.parser.OFPActionPopVlan(), actions[2])
        self.assertEqual(self.app.parser.NXActionResubmit(), actions[3])

    def test__get_dispatch_match(self):
        lswitch2 = self._create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = self._create_child_port()
        self.db_store.update(lport)
        segmentation = self._create_segmentation()
        self.db_store.update(segmentation)
        self.app.parser.OFPMatch.side_effect = SettingMock
        match = self.app._get_dispatch_match(segmentation)
        match_dict = match._dict
        self.assertEqual({'reg7': 33}, match_dict)

    def test__get_dispatch_actions(self):
        lswitch2 = self._create_2nd_lswitch()
        self.db_store.update(lswitch2)
        lport = self._create_child_port()
        self.db_store.update(lport)
        segmentation = self._create_segmentation()
        self.db_store.update(segmentation)
        self.app.parser.OFPActionSetField.side_effect = SettingMock
        self.app.parser.OFPActionOutput.side_effect = SettingMock
        actions = self.app._get_dispatch_actions(segmentation)
        self.assertEqual(self.app.parser.OFPActionPushVlan(), actions[0])
        self.assertEqual({'vlan_vid': 0x1007}, actions[1]._dict)
        self.assertEqual({'reg7': test_app_base.fake_local_port2.unique_key},
                         actions[2]._dict)
        self.assertEqual(self.app.parser.NXActionResubmit(), actions[3])
