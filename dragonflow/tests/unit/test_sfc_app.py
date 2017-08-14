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

from dragonflow.db.models import l2
from dragonflow.db.models import sfc
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base

lswitch1 = l2.LogicalSwitch(
    id='lswitch1',
    topic='topic1',
    version=10,
    unique_key=22,
)

fc1lport = l2.LogicalPort(
    id='lport1',
    topic='topic1',
    version=10,
    unique_key=22,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

fc2lport = l2.LogicalPort(
    id='lport2',
    topic='topic1',
    version=10,
    unique_key=23,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

fc1 = sfc.FlowClassifier(
    id='fc1',
    topic='topic1',
    unique_key=22,
    source_port='lport1',
)

fc2 = sfc.FlowClassifier(
    id='fc2',
    topic='topic1',
    unique_key=23,
    dest_port='lport2',
)

pp11ingress = l2.LogicalPort(
    id='pp11ingress',
    topic='topic1',
    version=10,
    unique_key=23,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

pp11egress = l2.LogicalPort(
    id='pp11egress',
    topic='topic1',
    version=10,
    unique_key=24,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

pp12ingress = l2.LogicalPort(
    id='pp12ingress',
    topic='topic1',
    version=10,
    unique_key=24,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

pp12egress = l2.LogicalPort(
    id='pp12egress',
    topic='topic1',
    version=10,
    unique_key=24,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

pp11 = sfc.PortPair(
    id='pp11',
    topic='topic1',
    ingress_port='pp11ingress',
    egress_port='pp11egress',
)

pp21 = sfc.PortPair(
    id='pp21',
    topic='topic1',
    ingress_port='pp11ingress',
    egress_port='pp11egress',
)

pp12 = sfc.PortPair(
    id='pp12',
    topic='topic1',
    ingress_port='pp12ingress',
    egress_port='pp12egress',
)

ppg1 = sfc.PortPairGroup(
    id='ppg1',
    topic='topic1',
    port_pairs=['pp11', 'pp12'],
)

ppg2 = sfc.PortPairGroup(
    id='ppg2',
    topic='topic1',
    port_pairs=['pp21'],
)

pc1 = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1'],
    port_pair_groups=['ppg1'],
)

pc1_fc_add = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1', 'fc2'],
    port_pair_groups=['ppg1'],
)

pc1_fc_remove = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=[],
    port_pair_groups=['ppg1'],
)

pc1_fc_change = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc2'],
    port_pair_groups=['ppg1'],
)

pc1_ppg_add = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1'],
    port_pair_groups=['ppg1', 'ppg2'],
)

pc1_ppg_remove = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1'],
    port_pair_groups=[],
)

pc1_ppg_change = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1'],
    port_pair_groups=['ppg2'],
)

l2_objs = (lswitch1, fc1lport, fc2lport, pp11ingress, pp11egress, pp12ingress,
           pp12egress)


class TestSfcApp(test_app_base.DFAppTestBase):
    apps_list = ['sfc']

    def setUp(self):
        super(TestSfcApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['sfc']
        self.app._install_flow_classifier_flows = mock.Mock()
        self.app._uninstall_flow_classifier_flows = mock.Mock()
        self.app._install_flow_classifier_local_port_flows = mock.Mock()
        self.app._uninstall_flow_classifier_local_port_flows = mock.Mock()
        self.driver = mock.Mock()

        def get_driver(pc):
            return self.driver
        self.app._get_port_chain_driver = get_driver

    @utils.with_local_objects(fc1, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_added(self):
        pc1.emit_created()
        self.app._install_flow_classifier_flows.assert_called_once_with(
            pc1, pc1.flow_classifiers[0])
        self.driver.install_port_pair_group_flows(
            pc1, pc1.port_pair_groups[0])
        self.driver.install_port_pair_egress_flows.assert_has_calls(
            [
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[0],
                ),
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[1],
                ),
            ]
        )
        self.assertEqual(
            2, self.driver.install_port_pair_group_flows.call_count)

    @utils.with_local_objects(fc1, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_deleted(self):
        pc1.emit_deleted()
        self.app._uninstall_flow_classifier_flows.assert_called_once_with(
            pc1, pc1.flow_classifiers[0])
        self.driver.uninstall_port_pair_group_flows(
            pc1, pc1.port_pair_groups[0])
        self.driver.uninstall_port_pair_egress_flows.assert_has_calls(
            [
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[0],
                ),
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[1],
                ),
            ]
        )
        self.assertEqual(
            2, self.driver.uninstall_port_pair_group_flows.call_count)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_add_fc(self):
        pc1_fc_add.emit_updated(pc1)

        self.app._install_flow_classifier_flows.assert_called_once_with(
            pc1_fc_add, pc1_fc_add.flow_classifiers[1])
        self.app._uninstall_flow_classifier_flows.assert_not_called()

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_remove_fc(self):
        pc1_fc_remove.emit_updated(pc1)

        self.app._install_flow_classifier_flows.assert_not_called()
        self.app._uninstall_flow_classifier_flows.assert_called_once_with(
            pc1, pc1.flow_classifiers[0])

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_replace_fc(self):
        pc1_fc_change.emit_updated(pc1)

        self.app._uninstall_flow_classifier_flows.assert_called_once_with(
            pc1, pc1.flow_classifiers[0])
        self.app._install_flow_classifier_flows.assert_called_once_with(
            pc1_fc_change, pc1_fc_change.flow_classifiers[0])

    @utils.with_local_objects(fc1, pp21, ppg2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_add_ppg(self):
        pc1_ppg_add.emit_updated(pc1)

        self.driver.install_port_pair_group_flows.assert_called_once_with(
            pc1_ppg_add, pc1_ppg_add.port_pair_groups[1])
        self.driver.uninstall_port_pair_group_flows.assert_not_called()

        self.driver.install_port_pair_egress_flows.assert_called_once_with(
            pc1_ppg_add,
            pc1_ppg_add.port_pair_groups[1],
            pc1_ppg_add.port_pair_groups[1].port_pairs[0],
        )
        self.driver.uninstall_port_pair_egress_flows.assert_not_called()

    @utils.with_local_objects(fc1, pp21, ppg2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_remove_ppg(self):
        pc1_ppg_remove.emit_updated(pc1)

        self.driver.install_port_pair_group_flows.assert_not_called()
        self.driver.uninstall_port_pair_group_flows.assert_called_once_with(
            pc1, pc1.port_pair_groups[0])

        self.driver.install_port_pair_egress_flows.assert_not_called()
        self.driver.uninstall_port_pair_egress_flows.assert_has_calls(
            [
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[0],
                ),
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[1],
                ),
            ],
        )
        self.assertEqual(
            2, self.driver.uninstall_port_pair_egress_flows.call_count)

    @utils.with_local_objects(fc1, pp21, ppg2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_chain_updated_replace_ppg(self):
        pc1_ppg_change.emit_updated(pc1)

        self.driver.install_port_pair_group_flows.assert_called_once_with(
            pc1_ppg_change, pc1_ppg_change.port_pair_groups[0])
        self.driver.uninstall_port_pair_group_flows.assert_called_once_with(
            pc1, pc1.port_pair_groups[0])

        self.driver.install_port_pair_egress_flows.assert_called_once_with(
            pc1_ppg_change,
            pc1_ppg_change.port_pair_groups[0],
            pc1_ppg_change.port_pair_groups[0].port_pairs[0],
        )
        self.driver.uninstall_port_pair_egress_flows.assert_has_calls(
            [
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[0],
                ),
                mock.call(
                    pc1,
                    pc1.port_pair_groups[0],
                    pc1.port_pair_groups[0].port_pairs[1],
                ),
            ],
        )
        self.assertEqual(
            2, self.driver.uninstall_port_pair_egress_flows.call_count)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_pair_ingress_port_added(self):
        pp11ingress.emit_bind_local()
        self.driver.uninstall_port_pair_group_flows.assert_called_once_with(
            pc1, ppg1)
        self.driver.install_port_pair_group_flows.assert_called_once_with(
            pc1, ppg1)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_pair_ingress_port_deleted(self):
        pp11ingress.emit_unbind_local()
        self.driver.uninstall_port_pair_group_flows.assert_called_once_with(
            pc1, ppg1)
        self.driver.install_port_pair_group_flows.assert_called_once_with(
            pc1, ppg1)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_pair_egress_port_added(self):
        pp11egress.emit_bind_local()
        self.driver.install_port_pair_egress_flows.assert_called_once_with(
            pc1, ppg1, pp11)
        self.driver.uninstall_port_pair_egress_flows.assert_not_called()

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_port_pair_egress_port_deleted(self):
        pp11egress.emit_unbind_local()
        self.driver.install_port_pair_egress_flows.assert_not_called()
        self.driver.uninstall_port_pair_egress_flows.assert_called_once_with(
            pc1, ppg1, pp11)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_flow_classifier_port_added(self):
        fc1lport.emit_bind_local()
        self.app._install_flow_classifier_local_port_flows\
            .assert_called_once_with(pc1, fc1)

    @utils.with_local_objects(fc1, fc2, pp11, pp12, ppg1, pc1, *l2_objs)
    def test_flow_classifier_port_deleted(self):
        fc1lport.emit_unbind_local()
        self.app._uninstall_flow_classifier_local_port_flows\
            .assert_called_once_with(pc1, fc1)
