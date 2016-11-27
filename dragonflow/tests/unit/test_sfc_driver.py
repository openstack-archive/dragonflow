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
from neutron_lib import context
from oslo_utils import importutils

from networking_sfc.db import flowclassifier_db as fdb
from networking_sfc.db import sfc_db
from networking_sfc.extensions import flowclassifier
from networking_sfc.extensions import sfc as sfc_ext
from networking_sfc.services.sfc.common import context as sfc_ctx
from networking_sfc.tests import base
from networking_sfc.tests.unit.db import test_flowclassifier_db
from networking_sfc.tests.unit.db import test_sfc_db

from dragonflow.db.models import sfc
from dragonflow.neutron.services.sfc import driver


class TestDfSfcDriver(
    test_sfc_db.SfcDbPluginTestCaseBase,
    test_flowclassifier_db.FlowClassifierDbPluginTestCaseBase,
    base.NeutronDbPluginV2TestCase
):
    resource_prefix_map = dict([
        (k, sfc_ext.SFC_PREFIX)
        for k in sfc_ext.RESOURCE_ATTRIBUTE_MAP.keys()
    ] + [
        (k, flowclassifier.FLOW_CLASSIFIER_PREFIX)
        for k in flowclassifier.RESOURCE_ATTRIBUTE_MAP.keys()
    ])

    def setUp(self):
        sfc_plugin = test_sfc_db.DB_SFC_PLUGIN_CLASS
        flowclassifier_plugin = (
            test_flowclassifier_db.DB_FLOWCLASSIFIER_PLUGIN_CLASS)

        service_plugins = {
            sfc_ext.SFC_EXT: sfc_plugin,
            flowclassifier.FLOW_CLASSIFIER_EXT: flowclassifier_plugin
        }
        sfc_db.SfcDbPlugin.supported_extension_aliases = [
            sfc_ext.SFC_EXT]
        sfc_db.SfcDbPlugin.path_prefix = sfc_ext.SFC_PREFIX
        fdb.FlowClassifierDbPlugin.supported_extension_aliases = [
            flowclassifier.FLOW_CLASSIFIER_EXT]
        fdb.FlowClassifierDbPlugin.path_prefix = (
            flowclassifier.FLOW_CLASSIFIER_PREFIX
        )
        super(TestDfSfcDriver, self).setUp(
            ext_mgr=None,
            plugin=None,
            service_plugins=service_plugins
        )
        self.sfc_plugin = importutils.import_object(sfc_plugin)
        self.flowclassifier_plugin = importutils.import_object(
            flowclassifier_plugin)
        ext_mgr = api_ext.PluginAwareExtensionManager(
            test_sfc_db.extensions_path,
            {
                sfc_ext.SFC_EXT: self.sfc_plugin,
                flowclassifier.FLOW_CLASSIFIER_EXT: self.flowclassifier_plugin
            }
        )
        app = config.load_paste_app('extensions_test_app')
        self.ext_api = api_ext.ExtensionMiddleware(app, ext_mgr=ext_mgr)
        self.ctx = context.get_admin_context()
        self.driver = driver.DfSfcDriver()
        self.driver.initialize()
        self.driver._nb_api = mock.Mock()

    def _get_ctx(self, cls, kwargs):
        return sfc_ctx.PortPairContext(
            self.sfc_plugin,
            self.ctx,
            kwargs,
        )

    def _get_pp_ctx(self, **kwargs):
        return self._get_ctx(sfc_ctx.PortPairContext, kwargs)

    def _get_ppg_ctx(self, **kwargs):
        return self._get_ctx(sfc_ctx.PortPairGroupContext, kwargs)

    def _get_pc_ctx(self, **kwargs):
        return self._get_ctx(sfc_ctx.PortChainContext, kwargs)

    def test_create_port_pair_postcommit(self):
        self.driver.create_port_pair_postcommit(
            self._get_pp_ctx(
                id='id1',
                project_id='id2',
                name='name',
                ingress='ingress-id',
                egress='egress-id',
                service_function_parameters={
                    'correlation': 'mpls',
                    'weight': 2,
                },
            ),
        )
        self.driver.nb_api.create.assert_called_once_with(
            sfc.PortPair(
                id='id1',
                topic='id2',
                name='name',
                ingress_port='ingress-id',
                egress_port='egress-id',
                correlation_mechanism=sfc.CORR_MPLS,
                weight=2,
            ),
        )

    def test_update_port_pair_postcommit(self):
        self.driver.update_port_pair_postcommit(
            self._get_pp_ctx(
                id='id1',
                project_id='id2',
                name='new-name',
            ),
        )
        self.driver.nb_api.update.assert_called_once_with(
            sfc.PortPair(
                id='id1',
                topic='id2',
                name='new-name',
            ),
        )

    def test_delete_port_pair_postcommit(self):
        self.driver.delete_port_pair_postcommit(
            self._get_pp_ctx(
                id='id1',
                project_id='id2',
            ),
        )
        self.driver.nb_api.delete.assert_called_once_with(
            sfc.PortPair(
                id='id1',
                topic='id2',
            ),
        )

    def test_create_port_pair_group_postcommit(self):
        self.driver.create_port_pair_group_postcommit(
            self._get_ppg_ctx(
                id='id1',
                project_id='id2',
                name='name',
                port_pairs=['pp1'],
            ),
        )
        self.driver.nb_api.create.assert_called_once_with(
            sfc.PortPairGroup(
                id='id1',
                topic='id2',
                name='name',
                port_pairs=['pp1'],
            ),
        )

    def test_update_port_pair_group_postcommit(self):
        self.driver.update_port_pair_group_postcommit(
            self._get_ppg_ctx(
                id='id1',
                project_id='id2',
                name='new-name',
                port_pairs=['pp1', 'pp2'],
            ),
        )
        self.driver.nb_api.update.assert_called_once_with(
            sfc.PortPairGroup(
                id='id1',
                topic='id2',
                name='new-name',
                port_pairs=['pp1', 'pp2'],
            ),
        )

    def test_delete_port_pair_group_postcommit(self):
        self.driver.delete_port_pair_group_postcommit(
            self._get_ppg_ctx(
                id='id1',
                project_id='id2',
            ),
        )
        self.driver.nb_api.delete.assert_called_once_with(
            sfc.PortPairGroup(
                id='id1',
                topic='id2',
            ),
        )

    def test_create_port_chain_postcommit(self):
        self.driver.create_port_chain_postcommit(
            self._get_pc_ctx(
                id='id1',
                project_id='id2',
                name='name',
                port_pair_groups=['ppg1', 'ppg2'],
                flow_classifiers=['fc1', 'fc2'],
                chain_id=7,
                chain_parameters={
                    'correlation': 'mpls',
                },
            ),
        )
        self.driver.nb_api.create.assert_called_once_with(
            sfc.PortChain(
                id='id1',
                topic='id2',
                name='name',
                port_pair_groups=['ppg1', 'ppg2'],
                flow_classifiers=['fc1', 'fc2'],
                chain_id=7,
                protocol=sfc.PROTO_MPLS,
            ),
        )

    def test_update_port_chain_postcommit(self):
        self.driver.update_port_chain_postcommit(
            self._get_pc_ctx(
                id='id1',
                project_id='id2',
                name='new-name',
                port_pair_groups=['ppg1', 'ppg2'],
                flow_classifiers=['fc1', 'fc2'],
            ),
        )
        self.driver.nb_api.update.assert_called_once_with(
            sfc.PortChain(
                id='id1',
                topic='id2',
                name='new-name',
                port_pair_groups=['ppg1', 'ppg2'],
                flow_classifiers=['fc1', 'fc2'],
            ),
        )

    def test_delete_port_chain_postcommit(self):
        self.driver.delete_port_chain_postcommit(
            self._get_pc_ctx(
                id='id1',
                project_id='id2',
            ),
        )
        self.driver.nb_api.delete.assert_called_once_with(
            sfc.PortChain(
                id='id1',
                topic='id2',
            ),
        )
