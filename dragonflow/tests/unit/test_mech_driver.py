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

"""Unit testing for dragonflow mechanism driver."""


import mock
import netaddr

from neutron.plugins.ml2 import config
from neutron.tests.unit.extensions import test_portsecurity
from neutron.tests.unit.plugins.ml2 import test_ext_portsecurity
from neutron.tests.unit.plugins.ml2 import test_plugin
from oslo_serialization import jsonutils

from dragonflow.db.models import host_route
from dragonflow.db.models import l2
from dragonflow.db.models import secgroups
from dragonflow.neutron.db.models import l2 as neutron_l2
from dragonflow.neutron.db.models import secgroups as neutron_secgroups
from dragonflow.tests.common import utils


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


class DFMechanismDriverTestCase(test_plugin.Ml2PluginV2TestCase):
    _mechanism_drivers = ['logger', 'df']
    _extension_drivers = ['port_security']

    def get_additional_service_plugins(self):
        p = super(DFMechanismDriverTestCase,
                  self).get_additional_service_plugins()
        p.update({'revision_plugin_name': 'revisions'})
        return p

    def setUp(self):
        config.cfg.CONF.set_override('extension_drivers',
                                     self._extension_drivers,
                                     group='ml2')
        mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
                   side_effect=utils.empty_wrapper).start()
        nbapi_instance = mock.patch('dragonflow.db.api_nb.NbApi').start()
        nbapi_instance.get_instance.return_value = mock.MagicMock()
        super(DFMechanismDriverTestCase, self).setUp()

        mm = self.driver.mechanism_manager
        self.mech_driver = mm.mech_drivers['df'].obj
        self.mech_driver.post_fork_initialize(None, None, None)


class TestDFMechDriver(DFMechanismDriverTestCase):

    def setUp(self):
        super(TestDFMechDriver, self).setUp()
        self.nb_api = self.mech_driver.nb_api

    def _test_create_security_group_revision(self):
        s = {'security_group': {'tenant_id': 'some_tenant', 'name': '',
                                'description': 'des'}}
        sg = self.driver.create_security_group(self.context, s)
        self.assertGreater(sg['revision_number'], 0)

        self.nb_api.create.assert_called_with(
            neutron_secgroups.security_group_from_neutron_obj(sg))
        return sg

    def test_create_security_group_revision(self):
        self._test_create_security_group_revision()

    def test_update_security_group_revision(self):
        sg = self._test_create_security_group_revision()
        data = {'security_group': {'name': 'updated'}}
        new_sg = self.driver.update_security_group(
            self.context, sg['id'], data)
        self.assertGreater(new_sg['revision_number'], sg['revision_number'])

        self.nb_api.update.assert_called_with(
            neutron_secgroups.security_group_from_neutron_obj(new_sg))

    def test_create_delete_sg_rule_revision(self):
        sg = self._test_create_security_group_revision()
        r = {'security_group_rule': {'tenant_id': 'some_tenant',
                                     'port_range_min': 80, 'protocol': 'tcp',
                                     'port_range_max': 90,
                                     'remote_ip_prefix': '0.0.0.0/0',
                                     'ethertype': 'IPv4',
                                     'remote_group_id': None,
                                     'direction': 'ingress',
                                     'security_group_id': sg['id']}}
        rule = self.driver.create_security_group_rule(self.context, r)
        new_sg = self.driver.get_security_group(self.context, sg['id'])
        self.assertGreater(new_sg['revision_number'], sg['revision_number'])
        self.nb_api.update.assert_called_with(
            neutron_secgroups.security_group_from_neutron_obj(new_sg))

        self.driver.delete_security_group_rule(self.context, rule['id'])
        newer_sg = self.driver.get_security_group(self.context, sg['id'])
        self.assertGreater(newer_sg['revision_number'],
                           new_sg['revision_number'])
        self.nb_api.update.assert_called_with(
            neutron_secgroups.security_group_from_neutron_obj(newer_sg))

    def _test_create_network_revision(self):
        with self.network() as n:
            network = n['network']
            self.assertGreater(network['revision_number'], 0)
            lswitch = neutron_l2.logical_switch_from_neutron_network(network)
            self.nb_api.create.assert_called_with(lswitch)
            return network, lswitch

    def test_create_network_revision(self):
        self._test_create_network_revision()

    def test_create_update_delete_subnet_network_revision(self):
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.assert_not_called()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network}, set_context=True) as s:
            subnet_id = s['subnet']['id']
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        lswitch.version = new_network['revision_number']
        self.nb_api.update.assert_called_once_with(lswitch)
        self.nb_api.update.reset_mock()

        data = {'subnet': {'name': 'updated'}}
        req = self.new_update_request('subnets', data, subnet_id)
        req.get_response(self.api)
        network = new_network
        new_network = self.driver.get_network(self.context, network['id'])
        new_lswitch = neutron_l2.logical_switch_from_neutron_network(
            new_network)
        updated_subnet = self.driver.get_subnet(self.context,
                                                subnet_id)
        new_lswitch.subnets = [neutron_l2.subnet_from_neutron_subnet(
            updated_subnet)]
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.nb_api.update.called_once_with(new_lswitch)
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        self.assertEqual(new_network['revision_number'],
                         lswitch.version)

        network = new_network
        req = self.new_delete_request('subnets', subnet_id)
        req.get_response(self.api)
        new_network = self.driver.get_network(self.context, network['id'])
        new_lswitch = neutron_l2.logical_switch_from_neutron_network(
            new_network)
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.nb_api.update.called_once_with(new_lswitch)
        self.assertEqual(new_network['revision_number'],
                         new_lswitch.version)

    def test_create_update_subnet_dhcp(self):
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network}, enable_dhcp=True,
                         set_context=True) as subnet:
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.assertIsInstance(lswitch, l2.LogicalSwitch)
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertTrue(df_subnet.enable_dhcp)
            self.assertIsNotNone(df_subnet.dhcp_ip)

            data = {'subnet': {'enable_dhcp': False}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertFalse(df_subnet.enable_dhcp)
            self.assertIsNone(df_subnet.dhcp_ip)

    def test_create_update_subnet_gateway_ip(self):
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network},
                         set_context=True) as subnet:
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.assertIsInstance(lswitch, l2.LogicalSwitch)
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()

            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertIsNotNone(df_subnet.gateway_ip)

            data = {'subnet': {'gateway_ip': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertIsNone(df_subnet.gateway_ip)

    def test_create_update_subnet_dnsnameserver(self):
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network}, set_context=True,
                         dns_nameservers=['1.1.1.1']) as subnet:
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.assertIsInstance(lswitch, l2.LogicalSwitch)
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()

            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertEqual([netaddr.IPAddress('1.1.1.1')],
                             df_subnet.dns_nameservers)

            data = {'subnet': {'dns_nameservers': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertEqual([], df_subnet.dns_nameservers)

    def test_create_update_subnet_hostroute(self):
        host_routes = [{'destination': '135.207.0.0/16', 'nexthop': '1.2.3.4'}]
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network}, host_routes=host_routes,
                         set_context=True) as subnet:
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.assertIsInstance(lswitch, l2.LogicalSwitch)
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertEqual([host_route.HostRoute(**hr)
                              for hr in host_routes],
                             df_subnet.host_routes)

            data = {'subnet': {'host_routes': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            df_subnet = lswitch.find_subnet(subnet['subnet']['id'])
            self.assertEqual([], df_subnet.host_routes)

    def test_create_update_port_allowed_address_pairs(self):
        kwargs = {'allowed_address_pairs':
                  [{"ip_address": "10.1.1.10"},
                   {"ip_address": "20.1.1.20",
                    "mac_address": "aa:bb:cc:dd:ee:ff"}]}
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet,
                           arg_list=('allowed_address_pairs',),
                           **kwargs) as p:
                port = p['port']
                self.nb_api.create.assert_called_once()
                lport = self.nb_api.create.call_args_list[0][0][0]
                self.nb_api.create.reset_mock()
                expected_aap = [
                    l2.AddressPair(ip_address="10.1.1.10",
                                   mac_address=port['mac_address']),
                    l2.AddressPair(ip_address="20.1.1.20",
                                   mac_address="aa:bb:cc:dd:ee:ff")]
                self.assertItemsEqual(
                    [aap.to_struct() for aap in expected_aap],
                    [aap.to_struct() for aap in lport.allowed_address_pairs])

                self.nb_api.update.reset_mock()
                data = {'port': {'allowed_address_pairs': []}}
                req = self.new_update_request(
                        'ports',
                        data, port['id'])
                req.get_response(self.api)

                self.nb_api.update.assert_called_once()
                lport = self.nb_api.update.call_args_list[0][0][0]

                self.assertEqual([], lport.allowed_address_pairs)

    def _test_create_update_port_security(self, enabled):
        kwargs = {'port_security_enabled': enabled}
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet,
                           arg_list=('port_security_enabled',),
                           **kwargs) as port:
                self.nb_api.create.assert_called_once()
                lport = self.nb_api.create.call_args_list[0][0][0]
                self.nb_api.create.reset_mock()
                self.nb_api.update.reset_mock()
                self.assertEqual(enabled,
                                 lport.port_security_enabled)

                data = {'port': {'mac_address': '00:00:00:00:00:01'}}
                req = self.new_update_request('ports',
                                              data, port['port']['id'])
                req.get_response(self.api)
                self.nb_api.update.assert_called_once()
                lport = self.nb_api.update.call_args_list[0][0][0]
                self.assertEqual(enabled,
                                 lport.port_security_enabled)

    def test_create_update_port_with_disabled_security(self):
        self._test_create_update_port_security(False)

    def test_create_update_port_with_enabled_security(self):
        self._test_create_update_port_security(True)

    def test_create_port_with_device_option(self):
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet, device_owner='fake_owner',
                           device_id='fake_id'):
                self.nb_api.create.assert_called_once()
                lport = self.nb_api.create.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual('fake_owner', lport.device_owner)
                self.assertEqual('fake_id', lport.device_id)

    def test_create_update_port_revision(self):
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet) as p:
                port = p['port']
                self.assertGreater(port['revision_number'], 0)
                self.nb_api.create.assert_called_once()
                lport = self.nb_api.create.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual(port['revision_number'], lport.version)

                self.nb_api.update.reset_mock()
                data = {'port': {'name': 'updated'}}
                req = self.new_update_request('ports', data, port['id'])
                req.get_response(self.api)
                prev_version = port['revision_number']
                port = self.driver.get_port(self.context, port['id'])
                self.assertGreater(port['revision_number'], prev_version)
                self.nb_api.update.assert_called_once()
                lport = self.nb_api.update.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual(port['revision_number'], lport.version)

    def test_delete_network(self):
        network, _lswitch = self._test_create_network_revision()
        req = self.new_delete_request('networks', network['id'])
        req.get_response(self.api)
        self.nb_api.delete.assert_called_with(l2.LogicalSwitch(
            id=network['id'], topic=network['tenant_id']))

    def test_create_update_remote_port(self):
        profile = {"port_key": "remote_port", "host_ip": "20.0.0.2"}
        profile_arg = {'binding:profile': profile}
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet,
                           arg_list=('binding:profile',),
                           **profile_arg) as port:
                port = port['port']
                self.nb_api.create.assert_called_once()
                lport = self.nb_api.create.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual(l2.BINDING_VTEP, lport.binding.type)
                # lport.chassis is a proxy, and we don't have a real database
                self.assertEqual("20.0.0.2", str(lport.binding.ip))

                self.nb_api.update.reset_mock()
                profile['host_ip'] = "20.0.0.20"
                data = {'port': {'binding:profile': profile}}
                req = self.new_update_request('ports', data, port['id'])
                req.get_response(self.api)
                self.nb_api.update.assert_called_once()
                lport = self.nb_api.update.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual(l2.BINDING_VTEP, lport.binding.type)
                self.assertEqual("20.0.0.20", str(lport.binding.ip))

    def test_delete_port(self):
        with self.port() as p:
            port = p['port']

        self.nb_api.delete.mock_reset()
        req = self.new_delete_request('ports', port['id'])
        req.get_response(self.api)
        self.nb_api.delete.assert_called_once()
        lport = self.nb_api.delete.call_args_list[0][0][0]
        self.assertIsInstance(lport, l2.LogicalPort)
        self.assertEqual(port['id'], lport.id)
        self.assertEqual(port['tenant_id'], lport.topic)

    def test_delete_security_group(self):
        sg = self._test_create_security_group_revision()
        self.driver.delete_security_group(self.context, sg['id'])
        self.nb_api.delete.assert_called_with(
            secgroups.SecurityGroup(id=sg['id'], topic=sg['project_id']))

    def test_update_subnet_with_disabled_dhcp(self):
        network, lswitch = self._test_create_network_revision()
        self.nb_api.update.reset_mock()
        self.nb_api.get.side_effect = nb_api_get_func(lswitch)
        with self.subnet(network={'network': network}, enable_dhcp=False) as s:
            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            self.nb_api.get.side_effect = nb_api_get_func(lswitch)
            self.nb_api.update.reset_mock()

            subnet = s['subnet']
            data = {'subnet': {'name': 'updated'}}
            req = self.new_update_request('subnets', data, subnet['id'])
            req.get_response(self.api)

            self.nb_api.update.assert_called_once()
            lswitch = self.nb_api.update.call_args_list[0][0][0]
            df_subnet = lswitch.find_subnet(subnet['id'])
            self.assertIsNone(df_subnet.dhcp_ip)

    def _test_create(self, port):

        self.nb_api.create.assert_called_once()
        lport = self.nb_api.create.call_args_list[0][0][0]
        self.assertIsInstance(lport, l2.LogicalPort)
        expected_edo = [{'value': "192.168.0.1",
                         'tag': 3},
                        {'value': "0.0.0.0/0,192.168.0.1",
                         'tag': 121}]

        for edo in expected_edo:
            self.assertEqual(edo['value'],
                             lport.dhcp_params.opts[edo['tag']])

    def _test_update(self, port):
        self.nb_api.update.reset_mock()
        data = {'port': {'extra_dhcp_opts': [{'opt_name': 'routers',
                                              'opt_value': None},
                                             {'opt_name': '121',
                                              'opt_value': None}]}}
        req = self.new_update_request(
            'ports',
            data, port['id'])
        req.get_response(self.api)
        self.nb_api.update.assert_called_once()
        lport = self.nb_api.update.call_args_list[0][0][0]
        self.assertIsInstance(lport, l2.LogicalPort)
        self.assertFalse(lport.dhcp_params.opts)

    def _test_invalid_args(self, port):
        data = {'port': {'extra_dhcp_opts': [{'opt_name': 'invalid',
                                              'opt_value': "test"},
                                             {'opt_name': '121',
                                              'opt_value': None}]}}
        req = self.new_update_request(
            'ports',
            data, port['id'])

        response = req.get_response(self.api)
        self.assertEqual(response.status_code, 400)
        error_type = jsonutils.loads(response.body)["NeutronError"]["type"]
        self.assertEqual(error_type, "InvalidInput")

    def test_create_update_port_extra_dhcp_opts(self):
        kwargs = {'extra_dhcp_opts':
                  [{'opt_value': "192.168.0.1", 'opt_name': "routers"},
                   {'opt_value': "0.0.0.0/0,192.168.0.1", 'opt_name': "121"}]}
        with self.subnet(enable_dhcp=False) as subnet:
            self.nb_api.create.reset_mock()
            with self.port(subnet=subnet,
                           arg_list=('extra_dhcp_opts',),
                           **kwargs) as p:
                port = p['port']

                self._test_create(port)
                self._test_update(port)
                self._test_invalid_args(port)


class TestDFMechansimDriverAllowedAddressPairs(
        test_plugin.TestMl2AllowedAddressPairs,
        DFMechanismDriverTestCase):
    pass


class TestDFMechansimDriverPortSecurity(
        test_ext_portsecurity.PSExtDriverTestCase,
        DFMechanismDriverTestCase):

    _extension_drivers = ['port_security']

    def setUp(self):
        config.cfg.CONF.set_override('extension_drivers',
                                     self._extension_drivers,
                                     group='ml2')
        # NOTE(xiaohhui): Make sure the core plugin is set to ml2, or else
        # the service plugin configured in get_additional_service_plugins
        # won't work.
        super(test_portsecurity.TestPortSecurity, self).setUp(plugin='ml2')
