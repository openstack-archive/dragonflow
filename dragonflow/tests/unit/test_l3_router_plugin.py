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

import itertools
import mock
from neutron.db.models import l3
from neutron.tests.unit.api import test_extensions
from neutron.tests.unit.extensions import test_l3
from neutron_lib import constants
from neutron_lib import context as nctx
from neutron_lib.plugins import directory

from dragonflow.db.models import l3 as df_l3
from dragonflow.neutron.db.models import l3 as neutron_l3
from dragonflow.tests.unit import test_mech_driver


def nb_api_get_funcs(*instances):
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

    def nb_api_create(inst):
        inst.on_create_pre()
        ids[inst.id] = inst

    def nb_api_update(inst):
        ids[inst.id].update(inst)

    return nb_api_get, nb_api_create, nb_api_update


class TestDFL3RouterPlugin(test_mech_driver.DFMechanismDriverTestCase,
                           test_l3.L3NatTestCaseMixin):

    l3_plugin = ('dragonflow.neutron.services.l3_router_plugin.'
                 'DFL3RouterPlugin')

    def setUp(self):
        super(TestDFL3RouterPlugin, self).setUp()
        self.l3p = directory.get_plugin('L3_ROUTER_NAT')
        self.nb_api = self.l3p.nb_api
        self.nb_api.get().unique_key = 5
        self.ext_api = test_extensions.setup_extensions_middleware(
            test_l3.L3TestExtensionManager()
        )

    def _test_create_router_revision(self):
        r = {'router': {'name': 'router', 'tenant_id': 'tenant',
                        'admin_state_up': True}}
        router = self.l3p.create_router(self.context, r)
        self.assertEqual(router['revision_number'], 0)

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

        nb_api_get, nb_api_create, nb_api_update = nb_api_get_funcs(lrouter)
        self.nb_api.get.side_effect = nb_api_get
        self.nb_api.update.side_effect = nb_api_update
        self.nb_api.create.side_effect = nb_api_create
        self.nb_api.driver.allocate_unique_key.side_effect = itertools.count()
        with self.subnet() as s:
            data = {'subnet_id': s['subnet']['id']}
            self.l3p.add_router_interface(self.context, router['id'], data)
            # NOTE(oanson) The calls to expire_all may need to be removed once
            # Neutron complete the move to EngineFacade. Currently they exist
            # to make sure we don't get stale Router objects with the old
            # version
            self.context.session.expire_all()
            router_with_int = self.l3p.get_router(self.context, router['id'])
            self.assertGreater(router_with_int['revision_number'],
                               old_version)
            lrouter.version = router_with_int['revision_number']
            self.nb_api.update.assert_has_calls([mock.call(lrouter)])
            # Second call is with the router lport
            self.nb_api.update.reset_mock()

            self.l3p.remove_router_interface(self.context, router['id'], data)
            self.context.session.expire_all()
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
                self.assertEqual(floatingip['revision_number'], 0)
                nb_fip = self.nb_api.create.call_args_list[-1][0][0]
                self.assertIsInstance(nb_fip, df_l3.FloatingIp)
                self.assertEqual(floatingip['id'], nb_fip.id)
                self.assertEqual(floatingip['tenant_id'], nb_fip.topic)
                self.assertEqual(floatingip['revision_number'],
                                 nb_fip.version)
        return floatingip

    def test_create_update_floatingip_revision(self):
        floatingip = self._test_create_floatingip_revision()
        old_version = floatingip['revision_number']
        floatingip['tenant_id'] = 'another_tenant'
        new_fip = self.l3p.update_floatingip(
            self.context, floatingip['id'], {'floatingip': floatingip})
        self.assertGreater(new_fip['revision_number'], old_version)
        nb_fip = self.nb_api.update.call_args_list[-1][0][0]
        self.assertIsInstance(nb_fip, df_l3.FloatingIp)
        self.assertEqual(new_fip['id'], nb_fip.id)
        self.assertEqual(new_fip['tenant_id'], nb_fip.topic)
        self.assertEqual(new_fip['revision_number'], nb_fip.version)

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

    def test_create_router_have_extra_attrs(self):
        r = {'router': {'name': 'router', 'tenant_id': 'tenant',
                        'admin_state_up': True}}
        router = self.l3p.create_router(self.context, r)
        record = (self.context.session.query(l3.Router).
                  filter_by(id=router['id']).
                  one())
        self.assertIsNotNone(record['extra_attributes'])

    def test_floatingip_create_not_assoc(self):
        with self.subnet() as subnet:
            with self.floatingip_no_assoc(subnet) as fip:
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_DOWN,
                    fip['floatingip']['status'],
                )

    def test_floatingip_create_port_status_down(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_DOWN)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_DOWN,
                    fip['floatingip']['status'],
                )

    def test_floatingip_create_port_status_active(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_ACTIVE)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_ACTIVE,
                    fip['floatingip']['status'],
                )

    def test_floatingip_port_updated_to_active(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_DOWN)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                self.l3p.core_plugin.update_port_status(
                    self.context, port['port']['id'],
                    constants.PORT_STATUS_ACTIVE)
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_ACTIVE,
                    self.l3p.get_floatingip(
                        self.context,
                        fip['floatingip']['id'],
                    )['status'],
                )

    def test_floatingip_port_updated_to_down(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_ACTIVE)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                self.l3p.core_plugin.update_port_status(
                    self.context, port['port']['id'],
                    constants.PORT_STATUS_DOWN)
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_DOWN,
                    self.l3p.get_floatingip(
                        self.context,
                        fip['floatingip']['id'],
                    )['status'],
                )

    def test_floatingip_update_disassoc(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_ACTIVE)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                floatingip_id = fip['floatingip']['id']
                self.l3p.update_floatingip(
                    self.context,
                    floatingip_id,
                    {'floatingip': {'port_id': None}},
                )
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_DOWN,
                    self.l3p.get_floatingip(
                        self.context,
                        floatingip_id,
                    )['status'],
                )

    def test_floatingip_update_assoc(self):
        with self.port() as port:
            self.l3p.core_plugin.update_port_status(
                self.context, port['port']['id'], constants.PORT_STATUS_ACTIVE)
            with self.floatingip_with_assoc(port_id=port['port']['id']) as fip:
                floatingip_id = fip['floatingip']['id']
                self.l3p.update_floatingip(
                    self.context,
                    floatingip_id,
                    {'floatingip': {'port_id': None}},
                )
                self.l3p.update_floatingip(
                    self.context,
                    floatingip_id,
                    {'floatingip': {'port_id': port['port']['id']}},
                )
                self.assertEqual(
                    constants.FLOATINGIP_STATUS_ACTIVE,
                    self.l3p.get_floatingip(
                        self.context,
                        floatingip_id,
                    )['status'],
                )
