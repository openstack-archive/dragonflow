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

lport1 = l2.LogicalPort(
    id='lport1',
    topic='topic1',
    version=10,
    unique_key=22,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

lport2 = l2.LogicalPort(
    id='lport2',
    topic='topic1',
    version=10,
    unique_key=24,
    lswitch='lswitch1',
    binding=test_app_base.local_binding,
)

lport3 = l2.LogicalPort(
    id='lport3',
    topic='topic1',
    version=10,
    unique_key=29,
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
    unique_key=12,
    dest_port='lport2',
)

fc3 = sfc.FlowClassifier(
    id='fc3',
    topic='topic1',
    unique_key=13,
    source_port='lport3',
)

pc1 = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1', 'fc2'],
)

pc1add = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc1', 'fc3', 'fc2'],
)

pc1remove = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc2'],
)

pc1replace = sfc.PortChain(
    id='pc1',
    topic='topic1',
    flow_classifiers=['fc3', 'fc2'],
)

fc10 = sfc.FlowClassifier(
    id='fc10',
    topic='topic1',
    unique_key=10,
    source_port='lport1',
)

fc11 = sfc.FlowClassifier(
    id='fc11',
    topic='topic1',
    unique_key=11,
    source_port='lport2',
)

fc12 = sfc.FlowClassifier(
    id='fc12',
    topic='topic1',
    unique_key=12,
    dest_port='lport1',
)

fc13 = sfc.FlowClassifier(
    id='fc13',
    topic='topic1',
    unique_key=13,
    dest_port='lport2',
)

pc2 = sfc.PortChain(
    id='pc2',
    topic='topic1',
    flow_classifiers=['fc10', 'fc11', 'fc12', 'fc14'],
)

l2_objs = (lswitch1, lport1, lport2, lport3)


class TestFcApp(test_app_base.DFAppTestBase):
    apps_list = ['fc']

    def setUp(self):
        super(TestFcApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['fc']
        for attribute in ('_install_flow_classifier',
                          '_uninstall_flow_classifier',
                          '_install_classification_flows',
                          '_install_dispatch_flows',
                          '_uninstall_classification_flows',
                          '_uninstall_dispatch_flows'):
            orig = getattr(self.app, attribute)
            p = mock.patch.object(self.app, attribute, side_effect=orig)
            self.addCleanup(p.stop)
            p.start()

    @utils.with_local_objects(fc1, fc2, fc3, pc1, *l2_objs)
    def test_pc_created(self):
        pc1.emit_created()
        self.app._install_flow_classifier.assert_has_calls(
            [
                mock.call(pc1.flow_classifiers[0]),
                mock.call(pc1.flow_classifiers[1]),
            ],
        )
        self.assertEqual(2, self.app._install_flow_classifier.call_count)
        self.app._uninstall_flow_classifier.assert_not_called()

    @utils.with_local_objects(fc1, fc2, fc3, pc1, *l2_objs)
    def test_pc_deleted(self):
        pc1.emit_deleted()
        self.app._install_flow_classifier.assert_not_called()
        self.app._uninstall_flow_classifier.assert_has_calls(
            [
                mock.call(pc1.flow_classifiers[0]),
                mock.call(pc1.flow_classifiers[1]),
            ],
        )
        self.assertEqual(2, self.app._uninstall_flow_classifier.call_count)

    @utils.with_local_objects(fc1, fc2, fc3, pc1, *l2_objs)
    def test_pc_updated_add_fc(self):
        pc1add.emit_updated(pc1)
        self.app._install_flow_classifier.assert_called_once_with(
            pc1add.flow_classifiers[1])
        self.app._uninstall_flow_classifier.assert_not_called()

    @utils.with_local_objects(fc1, fc2, fc3, pc1, *l2_objs)
    def test_pc_updated_remove_fc(self):
        pc1remove.emit_updated(pc1)
        self.app._install_flow_classifier.assert_not_called()
        self.app._uninstall_flow_classifier.assert_called_once_with(
            pc1.flow_classifiers[0])

    @utils.with_local_objects(fc1, fc2, fc3, pc1, *l2_objs)
    def test_pc_updated_replace_fc(self):
        pc1replace.emit_updated(pc1)
        self.app._install_flow_classifier.assert_called_once_with(
            pc1replace.flow_classifiers[0])
        self.app._uninstall_flow_classifier.assert_called_once_with(
            pc1.flow_classifiers[0])

    @utils.with_local_objects(fc10, fc11, fc12, fc13, pc2, *l2_objs)
    def test_install_flow_classifier(self):
        pc2.emit_created()

        # Installed only for dest-port and local source ports:
        self.app._install_classification_flows.has_calls(
            [
                mock.call(pc2.flow_classifiers[0]),
                mock.call(pc2.flow_classifiers[2]),
                mock.call(pc2.flow_classifiers[3]),
            ],
        )
        self.assertEqual(3, self.app._install_classification_flows.call_count)

        # Installed only for source-port and local dest ports:
        self.app._install_dispatch_flows.assert_has_calls(
            [
                mock.call(pc2.flow_classifiers[0]),
                mock.call(pc2.flow_classifiers[1]),
                mock.call(pc2.flow_classifiers[2]),
            ],
        )
        self.assertEqual(3, self.app._install_dispatch_flows.call_count)

    @utils.with_local_objects(fc10, fc11, fc12, fc13, pc2, *l2_objs)
    def test_uninstall_flow_classifier(self):
        pc2.emit_deleted()

        # Installed only for dest-port and local source ports:
        self.app._uninstall_classification_flows.has_calls(
            [
                mock.call(pc2.flow_classifiers[0]),
                mock.call(pc2.flow_classifiers[2]),
                mock.call(pc2.flow_classifiers[3]),
            ],
        )
        self.assertEqual(
            3, self.app._uninstall_classification_flows.call_count)

        # Installed only for source-port and local dest ports:
        self.app._uninstall_dispatch_flows.assert_has_calls(
            [
                mock.call(pc2.flow_classifiers[0]),
                mock.call(pc2.flow_classifiers[1]),
                mock.call(pc2.flow_classifiers[2]),
            ],
        )
        self.assertEqual(3, self.app._uninstall_dispatch_flows.call_count)

    @utils.with_local_objects(fc1, fc2, pc1, *l2_objs)
    def test_src_local_port_added(self):
        lport1.emit_bind_local()
        self.app._install_classification_flows.assert_called_once_with(fc1)
        self.app._install_dispatch_flows.assert_not_called()

    @utils.with_local_objects(fc1, fc2, pc1, *l2_objs)
    def test_src_local_port_removed(self):
        lport1.emit_unbind_local()
        self.app._uninstall_classification_flows.assert_called_once_with(fc1)
        self.app._uninstall_dispatch_flows.assert_not_called()

    @utils.with_local_objects(fc1, fc2, pc1, *l2_objs)
    def test_dest_local_port_added(self):
        lport2.emit_bind_local()
        self.app._install_classification_flows.assert_not_called()
        self.app._install_dispatch_flows.assert_called_once_with(fc2)

    @utils.with_local_objects(fc1, fc2, pc1, *l2_objs)
    def test_dest_local_port_removed(self):
        lport2.emit_unbind_local()
        self.app._uninstall_classification_flows.assert_not_called()
        self.app._uninstall_dispatch_flows.assert_called_once_with(fc2)
