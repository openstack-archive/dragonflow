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
from neutron.api import extensions as api_ext
from neutron.common import config
from neutron_lib import constants
from neutron_lib import context
from oslo_utils import importutils
import testtools

from networking_sfc.db import flowclassifier_db as fdb
from networking_sfc.extensions import flowclassifier
from networking_sfc.services.flowclassifier.common import context as fc_ctx
from networking_sfc.services.flowclassifier.common import exceptions as fc_exc
from networking_sfc.tests import base
from networking_sfc.tests.unit.db import test_flowclassifier_db

from dragonflow.db.models import sfc
from dragonflow.neutron.services.flowclassifier import driver


class TestDfFcDriver(
    test_flowclassifier_db.FlowClassifierDbPluginTestCaseBase,
    base.NeutronDbPluginV2TestCase
):

    resource_prefix_map = dict([
        (k, flowclassifier.FLOW_CLASSIFIER_PREFIX)
        for k in flowclassifier.RESOURCE_ATTRIBUTE_MAP.keys()
    ])

    def setUp(self):
        flowclassifier_plugin = (
            test_flowclassifier_db.DB_FLOWCLASSIFIER_PLUGIN_CLASS)

        service_plugins = {
            flowclassifier.FLOW_CLASSIFIER_EXT: flowclassifier_plugin
        }
        fdb.FlowClassifierDbPlugin.supported_extension_aliases = [
            flowclassifier.FLOW_CLASSIFIER_EXT]
        fdb.FlowClassifierDbPlugin.path_prefix = (
            flowclassifier.FLOW_CLASSIFIER_PREFIX
        )
        super(TestDfFcDriver, self).setUp(
            ext_mgr=None,
            plugin=None,
            service_plugins=service_plugins
        )
        self.flowclassifier_plugin = importutils.import_object(
            flowclassifier_plugin)
        ext_mgr = api_ext.PluginAwareExtensionManager(
            test_flowclassifier_db.extensions_path,
            {
                flowclassifier.FLOW_CLASSIFIER_EXT: self.flowclassifier_plugin
            }
        )
        app = config.load_paste_app('extensions_test_app')
        self.ext_api = api_ext.ExtensionMiddleware(app, ext_mgr=ext_mgr)
        self.ctx = context.get_admin_context()
        self.driver = driver.DfFlowClassifierDriver()
        self.driver.initialize()
        self.driver._nb_api = mock.Mock()

    def test_create_flow_classifier_precommit_source_port(self):
        with self.port(
            device_owner='compute',
            device_id='test',
        ) as port:
            with self.flow_classifier(flow_classifier={
                'name': 'test1',
                'logical_source_port': port['port']['id'],
            }) as fc:
                fc_context = fc_ctx.FlowClassifierContext(
                    self.flowclassifier_plugin, self.ctx,
                    fc['flow_classifier']
                )
                # Make sure validation step doesn't raise an exception
                self.driver.create_flow_classifier_precommit(fc_context)

    def test_create_flow_classifier_precommit_dest_port(self):
        with self.port(
            device_owner='compute',
            device_id='test',
        ) as port:
            with self.flow_classifier(flow_classifier={
                'name': 'test1',
                'logical_destination_port': port['port']['id'],
            }) as fc:
                fc_context = fc_ctx.FlowClassifierContext(
                    self.flowclassifier_plugin, self.ctx,
                    fc['flow_classifier']
                )
                # Make sure validation step doesn't raise an exception
                self.driver.create_flow_classifier_precommit(fc_context)

    def test_create_flow_classifier_precommit_both_ports(self):
        with self.port(
            device_owner='compute',
            device_id='test',
        ) as port:
            with self.flow_classifier(flow_classifier={
                'name': 'test1',
                'logical_source_port': port['port']['id'],
                'logical_destination_port': port['port']['id'],
            }) as fc:
                with testtools.ExpectedException(
                    fc_exc.FlowClassifierBadRequest
                ):
                    self.driver.create_flow_classifier_precommit(
                        fc_ctx.FlowClassifierContext(
                            self.flowclassifier_plugin, self.ctx,
                            fc['flow_classifier']
                        ),
                    )

    def test_create_flow_classifier_precommit_no_ports(self):
        with self.flow_classifier(flow_classifier={
            'name': 'test1',
            'logical_source_port': None,
            'logical_destination_port': None,
        }) as fc:
            fc_context = fc_ctx.FlowClassifierContext(
                self.flowclassifier_plugin, self.ctx,
                fc['flow_classifier']
            )
            with testtools.ExpectedException(fc_exc.FlowClassifierBadRequest):
                self.driver.create_flow_classifier_precommit(fc_context)

    def _get_fc_ctx(self, **kwargs):
        return fc_ctx.FlowClassifierContext(
            self.flowclassifier_plugin,
            self.ctx,
            kwargs,
        )

    def test_create_flow_classifier_postcommit(self):
        self.driver.create_flow_classifier_postcommit(
            self._get_fc_ctx(
                id='id1',
                project_id='id2',
                name='name',
                ethertype=constants.IPv4,
                source_ip_prefix='1.1.1.0/24',
                destination_ip_prefix='2.2.2.0/24',
                protocol=constants.PROTO_NAME_TCP,
                source_port_range_min=1111,
                source_port_range_max=2222,
                destination_port_range_min=3333,
                destination_port_range_max=4444,
                logical_source_port='port1',
                logical_destination_port='port2',

            ),
        )
        self.driver.nb_api.create.assert_called_once_with(
            sfc.FlowClassifier(
                id='id1',
                topic='id2',
                name='name',
                ether_type=constants.IPv4,
                source_cidr='1.1.1.0/24',
                dest_cidr='2.2.2.0/24',
                protocol=constants.PROTO_NAME_TCP,
                source_transport_ports=[1111, 2222],
                dest_transport_ports=[3333, 4444],
                source_port='port1',
                dest_port='port2',
            ),
        )

    def test_update_flow_classifier_postcommit(self):
        self.driver.update_flow_classifier_postcommit(
            self._get_fc_ctx(
                id='id1',
                project_id='id2',
                name='new-name',
            ),
        )
        self.driver.nb_api.update.assert_called_once_with(
            sfc.FlowClassifier(
                id='id1',
                topic='id2',
                name='new-name',
            ),
        )

    def test_delete_flow_classifier_postcommit(self):
        self.driver.delete_flow_classifier_postcommit(
            self._get_fc_ctx(
                id='id1',
                project_id='id2',
            ),
        )
        self.driver.nb_api.delete.assert_called_once_with(
            sfc.FlowClassifier(
                id='id1',
                topic='id2',
            ),
        )
