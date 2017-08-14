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
from neutron.conf.agent.metadata import config as metadata_config
from oslo_config import fixture as cfg_fixture

from dragonflow.controller.apps import metadata_service
from dragonflow.db.models import ovs
from dragonflow.tests import base as tests_base
from dragonflow.tests.unit import test_app_base


class TestMetadataServiceApp(test_app_base.DFAppTestBase):
    apps_list = ["metadata_service"]

    def setUp(self):
        super(TestMetadataServiceApp, self).setUp()
        self.meta_app = self.open_flow_app.dispatcher.apps['metadata_service']

    def test_metadata_interface_online(self):
        with mock.patch.object(self.meta_app,
                               '_add_tap_metadata_port') as mock_func:
            # Device without mac will not trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    ofport=1,
                    name=self.meta_app._interface,
                )
            )
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Other device update will not trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    ofport=1,
                    name='no-interface',
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                )
            )
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Device with mac will trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    ofport=1,
                    name=self.meta_app._interface,
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                )
            )
            mock_func.assert_called_once_with(1, "aa:bb:cc:dd:ee:ff")
            mock_func.reset_mock()

            # Duplicated updated will not trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port1',
                    ofport=1,
                    name=self.meta_app._interface,
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                )
            )
            mock_func.assert_not_called()


class TestMetadataServiceProxy(tests_base.BaseTestCase):
    def setUp(self):
        super(TestMetadataServiceProxy, self).setUp()
        self.nb_api = mock.Mock()
        self.cfg = self.useFixture(cfg_fixture.Config())
        self.cfg.register_opts(metadata_config.METADATA_PROXY_HANDLER_OPTS)
        self.cfg.config(nova_metadata_host='nova-host',
                        nova_metadata_port=443,
                        nova_metadata_protocol='https')
        self.proxy = metadata_service.DFMetadataProxyHandler(self.cfg.conf,
                                                             self.nb_api)

    def test_proxy_get_headers(self):
        req = mock.Mock()
        req.remote_addr = '128.0.0.3'
        req.headers = {}
        lport = mock.Mock()
        lport.topic = 'tenant1'
        lport.device_id = 'device_id1'
        lport.ip = netaddr.IPAddress('10.0.0.3')
        lport.unique_key = 3
        self.nb_api.get_all.return_value = [lport]
        with mock.patch.object(self.proxy, '_sign_instance_id') as sign:
            sign.return_value = 'instance_id'
            headers = self.proxy.get_headers(req)
            self.assertEqual({
                              'X-Forwarded-For': '10.0.0.3',
                              'X-Tenant-ID': 'tenant1',
                              'X-Instance-ID': 'device_id1',
                              'X-Instance-ID-Signature': 'instance_id',
                             }, headers)

    def test_proxy_get_host(self):
        host = self.proxy.get_host(mock.sentinel)
        self.assertEqual('nova-host:443', host)

    def test_proxy_get_scheme(self):
        scheme = self.proxy.get_scheme(mock.sentinel)
        self.assertEqual('https', scheme)
