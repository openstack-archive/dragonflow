# Copyright (c) 2016 OpenStack Foundation.
#
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
from neutron_lib import context as nctx
from neutron_lib.plugins import directory
from oslo_config import cfg
import testtools

from dragonflow.common import utils as df_utils
from dragonflow.db import models
from dragonflow.neutron.db.models import l3 as neutron_l3
from dragonflow.tests.unit import test_mech_driver


def nb_api_get_func(*instances):
    """
    Create an method that can be used to override the mock's nb_api's get
    to return objects that should exist, e.g. instances that were created
    with create (and verified with the relevant assert)
    :param instances:   An iterable of instances that should exist in nb_api
    :type instances:    iterable of instances
    """
    ids = {instance.id: instance for instance in instances}

    def nb_api_get(inst):
        try:
            return ids[inst.id]
        except KeyError:
            return mock.MagicMock(name='NbApi.get_instance().get()')
    return nb_api_get


class TestDFL3RouterPlugin(test_mech_driver.DFMechanismDriverTestCase):

    l3_plugin = ('dragonflow.neutron.services.l3_router_plugin.'
                 'DFL3RouterPlugin')

    def setUp(self):
        super(TestDFL3RouterPlugin, self).setUp()
        self.l3p = directory.get_plugin('L3_ROUTER_NAT')
        self.nb_api = self.l3p.nb_api

    @mock.patch('neutron.db.l3_db.L3_NAT_db_mixin.create_floatingip')
    def test_create_floatingip_failed_in_neutron(self, func):
        func.side_effect = Exception("The exception")
        with testtools.ExpectedException(Exception):
            self.l3p.create_floatingip(self.context, mock.ANY)

    def _test_create_router_revision(self):
        r = {'router': {'name': 'router', 'tenant_id': 'tenant',
                        'admin_state_up': True}}
        router = self.l3p.create_router(self.context, r)
        self.assertGreater(router['revision_number'], 0)

        lrouter = neutron_l3.logical_router_from_neutron_router(router)
        self.nb_api.create.assert_called_once_with(lrouter)
        return router, lrouter

    def test_create_update_router_revision(self):
        router, _ = self._test_create_router_revision()
        old_version = router['revision_number']
        router['name'] = 'another_router'
        new_router = self.l3p.update_router(
            self.context, router['id'], {'router': router})
        self.assertGreater(new_router['revision_number'], old_version)

    def test_add_delete_router_interface_revision(self):
        router, lrouter = self._test_create_router_revision()
        old_version = router['revision_number']
        # TODO(xiaohhui): This needs to be cleaned once lport has
        # migrated to new model.
        mock_lport = mock.Mock()
        mock_lport.get_unique_key.return_value = 1
        self.nb_api.get_logical_port.return_value = mock_lport

        self.nb_api.get.side_effect = nb_api_get_func(lrouter)
        with self.subnet() as s:
            data = {'subnet_id': s['subnet']['id']}
            self.l3p.add_router_interface(self.context, router['id'], data)
            router_with_int = self.l3p.get_router(self.context, router['id'])
            self.assertGreater(router_with_int['revision_number'],
                               old_version)
            lrouter.version = router_with_int['revision_number']
            self.nb_api.update.assert_called_once_with(lrouter)
            self.nb_api.update.reset_mock()

            self.l3p.remove_router_interface(self.context, router['id'], data)
            router_without_int = self.l3p.get_router(self.context,
                                                     router['id'])
            self.assertGreater(router_without_int['revision_number'],
                               router_with_int['revision_number'])
            lrouter.version = router_without_int['revision_number']
            self.nb_api.update.assert_called_once_with(lrouter)

    def _test_create_floatingip_revision(self):
        kwargs = {'arg_list': ('router:external',),
                  'router:external': True}
        with self.network(**kwargs) as n:
            with self.subnet(network=n):
                floatingip = self.l3p.create_floatingip(
                    self.context,
                    {'floatingip': {'floating_network_id': n['network']['id'],
                                    'tenant_id': n['network']['tenant_id']}})
                self.assertGreater(floatingip['revision_number'], 0)
                self.nb_api.create_floatingip.assert_called_once_with(
                    id=floatingip['id'],
                    topic=floatingip['tenant_id'],
                    version=floatingip['revision_number'],
                    name=mock.ANY, floating_ip_address=mock.ANY,
                    floating_network_id=mock.ANY, router_id=mock.ANY,
                    port_id=mock.ANY, fixed_ip_address=mock.ANY,
                    status=mock.ANY, floating_port_id=mock.ANY,
                    floating_mac_address=mock.ANY,
                    external_gateway_ip=mock.ANY,
                    external_cidr=mock.ANY)
        return floatingip

    def test_create_update_floatingip_revision(self):
        floatingip = self._test_create_floatingip_revision()
        old_version = floatingip['revision_number']
        floatingip['tenant_id'] = 'another_tenant'
        new_fip = self.l3p.update_floatingip(
            self.context, floatingip['id'], {'floatingip': floatingip})
        self.assertGreater(new_fip['revision_number'], old_version)
        self.nb_api.update_floatingip.assert_called_once_with(
            id=floatingip['id'], topic=new_fip['tenant_id'],
            notify=True, name=mock.ANY, router_id=mock.ANY,
            port_id=mock.ANY, version=new_fip['revision_number'],
            fixed_ip_address=mock.ANY)

    def test_create_floatingip_with_normal_user(self):
        normal_context = nctx.Context(is_admin=False, overwrite=False)
        kwargs = {'arg_list': ('router:external',),
                  'router:external': True}
        with self.network(**kwargs) as n:
            with self.subnet(network=n):
                floatingip = self.l3p.create_floatingip(
                    normal_context,
                    {'floatingip': {'floating_network_id': n['network']['id'],
                                    'tenant_id': n['network']['tenant_id']}})
                self.assertTrue(floatingip)

    def test_notify_update_fip_status(self):
        cfg.CONF.set_override('port_status_notifier',
                              'redis_port_status_notifier_driver',
                              group='df')
        notifier = df_utils.load_driver(
            cfg.CONF.df.port_status_notifier,
            df_utils.DF_PORT_STATUS_DRIVER_NAMESPACE)

        kwargs = {'arg_list': ('router:external',),
                  'router:external': True}
        with self.network(**kwargs) as n:
            with self.subnet(network=n):
                floatingip = self.l3p.create_floatingip(
                    self.context,
                    {'floatingip': {'floating_network_id': n['network']['id'],
                                    'tenant_id': n['network']['tenant_id']}})

        self.assertEqual(n_const.FLOATINGIP_STATUS_DOWN, floatingip['status'])
        notifier.port_status_callback(models.Floatingip.table_name,
                                      floatingip['id'],
                                      "update",
                                      n_const.FLOATINGIP_STATUS_ACTIVE)
        floatingip = self.l3p.get_floatingip(self.context, floatingip['id'])
        self.assertEqual(n_const.FLOATINGIP_STATUS_ACTIVE,
                         floatingip['status'])
