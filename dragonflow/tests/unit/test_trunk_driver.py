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

from neutron.services.trunk import drivers as trunk_drivers
from neutron.services.trunk import plugin as trunk_plugin

from dragonflow.neutron.services.trunk import driver
from dragonflow.tests.unit import test_mech_driver


class TestDFTrunkDriver(test_mech_driver.DFMechanismDriverTestCase):
    def setUp(self):
        self._extension_drivers.append('qos')
        super(TestDFTrunkDriver, self).setUp()
        drivers_patch = mock.patch.object(trunk_drivers, 'register')
        self.addCleanup(drivers_patch.stop)
        drivers_patch.start()

        compat_patch = mock.patch.object(
            trunk_plugin.TrunkPlugin, 'check_compatibility')
        self.addCleanup(compat_patch.stop)
        compat_patch.start()

        self.trunk_plugin = trunk_plugin.TrunkPlugin()
        self.trunk_plugin.add_segmentation_type('vlan', lambda x: True)
        cfg.CONF.set_override('mechanism_drivers', 'df', group='ml2')
        self.df_driver = self.mech_driver.trunk_driver

    def test_driver_is_loaded(self):
        cfg.CONF.set_override('mechanism_drivers',
                              'df', group='ml2')
        rie = mock.patch.object(driver.DragonflowDriver,
                                '_register_init_events')
        rie.start()
        self.addCleanup(rie.stop)
        df_driver = driver.DragonflowDriver()
        self.assertTrue(df_driver.is_loaded)

    def test_driver_is_not_loaded(self):
        cfg.CONF.set_override('mechanism_drivers',
                              'my_foo_plugin', group='ml2')
        rie = mock.patch.object(driver.DragonflowDriver,
                                '_register_init_events')
        rie.start()
        self.addCleanup(rie.stop)
        df_driver = driver.DragonflowDriver()
        self.assertFalse(df_driver.is_loaded)

    def test_driver_create_delete_subport(self):
        # Create parent port
        # Create sub port
        # Create trunk port
        # create subport
        # assert nb_api
        # delete subport
        # assert nb_api
        nb_api = self.mech_driver.nb_api
        self.assertEqual(nb_api, self.df_driver.nb_api)
        with self.port() as parent, self.port() as subport:
            trunk = self.trunk_plugin.create_trunk(self.context, {
                'trunk': {
                    'port_id': parent['port']['id'],
                    'tenant_id': 'project1',
                    'sub_ports': [],
                }
            })
            nb_api.create.reset_mock()
            nb_api.delete.reset_mock()
            subport = {'segmentation_type': 'vlan',
                       'segmentation_id': 123,
                       'port_id': subport['port']['id']}
            self.trunk_plugin.add_subports(
                self.context, trunk['id'], {'sub_ports': [subport]})
            nb_api.create.assert_called_once()
            self.trunk_plugin.remove_subports(
                self.context, trunk['id'], {'sub_ports': [subport]})
            nb_api.delete.assert_called_once()
