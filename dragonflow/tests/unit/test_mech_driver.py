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
import six

from neutron.plugins.ml2 import config
from neutron.tests.unit.extensions import test_portsecurity
from neutron.tests.unit.plugins.ml2 import test_ext_portsecurity
from neutron.tests.unit.plugins.ml2 import test_plugin


class empty_wrapper(object):
    def __init__(self, type):
        pass

    def __call__(self, f):
        @six.wraps(f)
        def wrapped_f(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapped_f


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
                   side_effect=empty_wrapper).start()
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

        self.nb_api.create_security_group.assert_called_with(
            id=sg['id'], topic=sg['tenant_id'],
            name=sg['name'], rules=sg['security_group_rules'],
            version=sg['revision_number'])
        return sg

    def test_create_security_group_revision(self):
        self._test_create_security_group_revision()

    def test_update_security_group_revision(self):
        sg = self._test_create_security_group_revision()
        data = {'security_group': {'name': 'updated'}}
        new_sg = self.driver.update_security_group(
            self.context, sg['id'], data)
        self.assertGreater(new_sg['revision_number'], sg['revision_number'])

        self.nb_api.update_security_group.assert_called_with(
            id=sg['id'], topic=sg['tenant_id'],
            name='updated', rules=new_sg['security_group_rules'],
            version=new_sg['revision_number'])

    def test_create_delete_sg_rule_revision(self):
        sg = self._test_create_security_group_revision()
        r = {'security_group_rule': {'tenant_id': 'some_tenant',
                                     'port_range_min': 80, 'protocol': 6,
                                     'port_range_max': 90,
                                     'remote_ip_prefix': '0.0.0.0/0',
                                     'ethertype': 'IPv4',
                                     'remote_group_id': None,
                                     'direction': 'ingress',
                                     'security_group_id': sg['id']}}
        rule = self.driver.create_security_group_rule(self.context, r)
        new_sg = self.driver.get_security_group(self.context, sg['id'])
        self.assertGreater(new_sg['revision_number'], sg['revision_number'])
        self.nb_api.add_security_group_rules.assert_called_with(
            sg['id'], sg['tenant_id'],
            sg_rules=[rule], sg_version=new_sg['revision_number'])

        self.driver.delete_security_group_rule(self.context, rule['id'])
        newer_sg = self.driver.get_security_group(self.context, sg['id'])
        self.assertGreater(newer_sg['revision_number'],
                           new_sg['revision_number'])
        self.nb_api.delete_security_group_rule.assert_called_with(
            sg['id'], rule['id'], sg['tenant_id'],
            sg_version=newer_sg['revision_number'])

    def _test_create_network_revision(self):
        with self.network() as n:
            network = n['network']
            self.assertGreater(network['revision_number'], 0)
            self.nb_api.create_lswitch.assert_called_with(
                id=network['id'], topic=network['tenant_id'],
                name=network['name'],
                network_type=network['provider:network_type'],
                segmentation_id=network['provider:segmentation_id'],
                physical_network=network['provider:physical_network'],
                router_external=network['router:external'],
                mtu=network['mtu'], version=network['revision_number'],
                subnets=[],
                qos_policy_id=None)
            return network

    def test_create_network_revision(self):
        self._test_create_network_revision()

    def test_create_update_delete_subnet_network_revision(self):
        network = self._test_create_network_revision()
        with self.subnet(network={'network': network}, set_context=True) as s:
            subnet_id = s['subnet']['id']
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.assertTrue(self.nb_api.add_subnet.called)
        called_args = self.nb_api.add_subnet.call_args_list[0][1]
        self.assertEqual(new_network['revision_number'],
                         called_args.get('nw_version'))

        data = {'subnet': {'name': 'updated'}}
        req = self.new_update_request('subnets', data, subnet_id)
        req.get_response(self.api)
        network = new_network
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.assertTrue(self.nb_api.update_subnet.called)
        called_args = self.nb_api.update_subnet.call_args_list[0][1]
        self.assertEqual(new_network['revision_number'],
                         called_args.get('nw_version'))

        network = new_network
        req = self.new_delete_request('subnets', subnet_id)
        req.get_response(self.api)
        network = new_network
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.assertTrue(self.nb_api.delete_subnet.called)
        called_args = self.nb_api.delete_subnet.call_args_list[0][1]
        self.assertEqual(new_network['revision_number'],
                         called_args.get('nw_version'))

    def test_create_update_subnet_dhcp(self):
        with self.subnet(enable_dhcp=True, set_context=True,
                         tenant_id='test') as subnet:
            self.assertTrue(self.nb_api.add_subnet.called)
            called_args_dict = (
                self.nb_api.add_subnet.call_args_list[0][1])
            self.assertTrue(called_args_dict.get('enable_dhcp'))
            self.assertIsNotNone(called_args_dict.get('dhcp_ip'))

            data = {'subnet': {'enable_dhcp': False}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.assertTrue(self.nb_api.update_subnet.called)
            called_args_dict = (
                self.nb_api.update_subnet.call_args_list[0][1])
            self.assertFalse(called_args_dict.get('enable_dhcp'))
            self.assertIsNone(called_args_dict.get('dhcp_ip'))

    def test_create_update_subnet_gateway_ip(self):
        with self.subnet(set_context=True, tenant_id='test') as subnet:
            self.assertTrue(self.nb_api.add_subnet.called)
            called_args_dict = (
                self.nb_api.add_subnet.call_args_list[0][1])
            self.assertIsNotNone(called_args_dict.get('gateway_ip'))

            data = {'subnet': {'gateway_ip': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.assertTrue(self.nb_api.update_subnet.called)
            called_args_dict = (
                self.nb_api.update_subnet.call_args_list[0][1])
            self.assertIsNone(called_args_dict.get('gateway_ip'))

    def test_create_update_subnet_dnsnameserver(self):
        with self.subnet(dns_nameservers=['1.1.1.1'],
                         set_context=True, tenant_id='test') as subnet:
            self.assertTrue(self.nb_api.add_subnet.called)
            called_args_dict = (
                self.nb_api.add_subnet.call_args_list[0][1])
            self.assertEqual(['1.1.1.1'],
                             called_args_dict.get('dns_nameservers'))

            data = {'subnet': {'dns_nameservers': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.assertTrue(self.nb_api.update_subnet.called)
            called_args_dict = (
                self.nb_api.update_subnet.call_args_list[0][1])
            self.assertEqual([], called_args_dict.get('dns_nameservers'))

    def test_create_update_subnet_hostroute(self):
        host_routes = [{'destination': '135.207.0.0/16', 'nexthop': '1.2.3.4'}]
        with self.subnet(host_routes=host_routes,
                         set_context=True, tenant_id='test') as subnet:
            self.assertTrue(self.nb_api.add_subnet.called)
            called_args_dict = (
                self.nb_api.add_subnet.call_args_list[0][1])
            self.assertEqual(host_routes,
                             called_args_dict.get('host_routes'))

            data = {'subnet': {'host_routes': None}}
            req = self.new_update_request('subnets',
                                          data, subnet['subnet']['id'])
            req.get_response(self.api)
            self.assertTrue(self.nb_api.update_subnet.called)
            called_args_dict = (
                self.nb_api.update_subnet.call_args_list[0][1])
            self.assertEqual([], called_args_dict.get('host_routes'))

    def test_create_update_port_allowed_address_pairs(self):
        kwargs = {'allowed_address_pairs':
                  [{"ip_address": "10.1.1.10"},
                   {"ip_address": "20.1.1.20",
                    "mac_address": "aa:bb:cc:dd:ee:ff"}]}
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet,
                           arg_list=('allowed_address_pairs',),
                           **kwargs) as p:
                port = p['port']
                self.assertTrue(self.nb_api.create_lport.called)
                called_args = self.nb_api.create_lport.call_args_list[0][1]
                expected_aap = [{"ip_address": "10.1.1.10",
                                 "mac_address": port['mac_address']},
                                {"ip_address": "20.1.1.20",
                                 "mac_address": "aa:bb:cc:dd:ee:ff"}]
                self.assertItemsEqual(expected_aap,
                                      called_args.get("allowed_address_pairs"))

                data = {'port': {'allowed_address_pairs': []}}
                req = self.new_update_request(
                        'ports',
                        data, port['id'])
                req.get_response(self.api)
                self.assertTrue(self.nb_api.update_lport.called)
                called_args = self.nb_api.update_lport.call_args_list[0][1]
                self.assertEqual([], called_args.get("allowed_address_pairs"))

    def _test_create_update_port_security(self, enabled):
        kwargs = {'port_security_enabled': enabled}
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet,
                           arg_list=('port_security_enabled',),
                           **kwargs) as port:
                self.assertTrue(self.nb_api.create_lport.called)
                called_args_dict = (
                    self.nb_api.create_lport.call_args_list[0][1])
                self.assertEqual(enabled,
                                 called_args_dict.get('port_security_enabled'))

                data = {'port': {'mac_address': '00:00:00:00:00:01'}}
                req = self.new_update_request('ports',
                                              data, port['port']['id'])
                req.get_response(self.api)
                self.assertTrue(self.nb_api.update_lport.called)
                called_args_dict = (
                    self.nb_api.update_lport.call_args_list[0][1])
                self.assertEqual(enabled,
                                 called_args_dict.get('port_security_enabled'))

    def test_create_update_port_with_disabled_security(self):
        self._test_create_update_port_security(False)

    def test_create_update_port_with_enabled_security(self):
        self._test_create_update_port_security(True)

    def test_create_port_with_device_option(self):
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet, device_owner='fake_owner',
                           device_id='fake_id'):
                self.assertTrue(self.nb_api.create_lport.called)
                called_args_dict = (
                    self.nb_api.create_lport.call_args_list[0][1])
                self.assertEqual('fake_owner',
                                 called_args_dict.get('device_owner'))
                self.assertEqual('fake_id',
                                 called_args_dict.get('device_id'))

    def test_create_update_port_revision(self):
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet) as p:
                port = p['port']
                self.assertGreater(port['revision_number'], 0)
                self.assertTrue(self.nb_api.create_lport.called)
                called_args_dict = (
                    self.nb_api.create_lport.call_args_list[0][1])
                self.assertEqual(port['revision_number'],
                                 called_args_dict.get('version'))

                data = {'port': {'name': 'updated'}}
                req = self.new_update_request('ports', data, port['id'])
                req.get_response(self.api)
                prev_version = port['revision_number']
                port = self.driver.get_port(self.context, port['id'])
                self.assertGreater(port['revision_number'], prev_version)
                self.assertTrue(self.nb_api.update_lport.called)
                called_args_dict = (
                    self.nb_api.update_lport.call_args_list[0][1])
                self.assertEqual(port['revision_number'],
                                 called_args_dict.get('version'))

    def test_delete_network(self):
        network = self._test_create_network_revision()
        req = self.new_delete_request('networks', network['id'])
        req.get_response(self.api)
        self.nb_api.delete_lswitch.assert_called_with(
            id=network['id'], topic=network['tenant_id'])

    def test_create_update_remote_port(self):
        profile = {"port_key": "remote_port", "host_ip": "20.0.0.2"}
        profile_arg = {'binding:profile': profile}
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet,
                           arg_list=('binding:profile',),
                           **profile_arg) as port:
                port = port['port']
                self.assertTrue(self.nb_api.create_lport.called)
                called_args_dict = (
                    self.nb_api.create_lport.call_args_list[0][1])
                self.assertTrue(called_args_dict.get('remote_vtep'))
                self.assertEqual("20.0.0.2",
                                 called_args_dict.get('chassis'))

                profile['host_ip'] = "20.0.0.20"
                data = {'port': {'binding:profile': profile}}
                req = self.new_update_request('ports', data, port['id'])
                req.get_response(self.api)
                self.assertTrue(self.nb_api.update_lport.called)
                called_args_dict = (
                    self.nb_api.update_lport.call_args_list[0][1])
                self.assertTrue(called_args_dict.get('remote_vtep'))
                self.assertEqual("20.0.0.20",
                                 called_args_dict.get('chassis'))

    def test_delete_port(self):
        with self.port() as p:
            port = p['port']

        req = self.new_delete_request('ports', port['id'])
        req.get_response(self.api)
        self.nb_api.delete_lport.assert_called_with(
            id=port['id'], topic=port['tenant_id'])

    def test_delete_security_group(self):
        sg = self._test_create_security_group_revision()
        self.driver.delete_security_group(self.context, sg['id'])
        self.nb_api.delete_security_group.assert_called_with(
            sg['id'], topic=sg['tenant_id'])

    def test_update_subnet_with_disabled_dhcp(self):
        with self.subnet(enable_dhcp=False) as s:
            self.nb_api.update_subnet.reset_mock()
            subnet = s['subnet']
            data = {'subnet': {'name': 'updated'}}
            req = self.new_update_request('subnets', data, subnet['id'])
            req.get_response(self.api)
            self.assertTrue(self.nb_api.update_subnet.called)
            called_args = self.nb_api.update_subnet.call_args_list[0][1]
            self.assertEqual('updated', called_args.get('name'))
            self.assertIsNone(called_args.get('dhcp_ip'))

    def test_create_update_port_extra_dhcp_opts(self):
        kwargs = {'extra_dhcp_opts':
                  [{'opt_value': "192.168.0.1", 'opt_name': "3"},
                   {'opt_value': "0.0.0.0/0,192.168.0.1", 'opt_name': "121"}]}
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet,
                           arg_list=('extra_dhcp_opts',),
                           **kwargs) as p:
                port = p['port']
                self.assertTrue(self.nb_api.create_lport.called)
                called_args = self.nb_api.create_lport.call_args_list[0][1]
                expected_edo = [{'opt_value': u"192.168.0.1",
                                 'opt_name': u"3",
                                 'ip_version': 4},
                                {'opt_value': u"0.0.0.0/0,192.168.0.1",
                                 'opt_name': u"121",
                                 'ip_version': 4}]
                self.assertItemsEqual(expected_edo,
                                      called_args.get("extra_dhcp_opts"))

                data = {'port': {'extra_dhcp_opts': [{'opt_name': '3',
                                                      'opt_value': None},
                                                     {'opt_name': '121',
                                                      'opt_value': None}]}}
                req = self.new_update_request(
                        'ports',
                        data, port['id'])
                req.get_response(self.api)
                self.assertTrue(self.nb_api.update_lport.called)
                called_args = self.nb_api.update_lport.call_args_list[0][1]
                self.assertEqual([], called_args.get("extra_dhcp_opts"))


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
