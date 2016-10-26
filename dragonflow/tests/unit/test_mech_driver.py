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

    def get_additional_service_plugins(self):
        p = super(DFMechanismDriverTestCase,
                  self).get_additional_service_plugins()
        p.update({'revision_plugin_name': 'revisions'})
        return p

    def setUp(self):
        mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
                   side_effect=empty_wrapper).start()
        nbapi_instance = mock.patch('dragonflow.db.api_nb.NbApi').start()
        nbapi_instance.get_instance.return_value = mock.MagicMock()
        super(DFMechanismDriverTestCase, self).setUp()


class TestDFMechDriver(DFMechanismDriverTestCase):

    def setUp(self):
        super(TestDFMechDriver, self).setUp()
        mm = self.driver.mechanism_manager
        self.mech_driver = mm.mech_drivers['df'].obj
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
        self.nb_api.create_security_group_rules.assert_called_with(
            sg['id'], sg['tenant_id'],
            sg_rules=[rule], sg_version=new_sg['revision_number'])

        self.mech_driver._get_security_group_id_from_security_group_rule = (
            mock.Mock(return_value=sg['id']))

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
                subnets=[])
            return network

    def test_create_network_revision(self):
        self._test_create_network_revision()

    def test_create_update_delete_subnet_network_revision(self):
        network = self._test_create_network_revision()
        with self.subnet(network={'network': network}) as s:
            subnet = s['subnet']
            subnet_id = s['subnet']['id']

        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.nb_api.create_subnet.assert_called_with(
            subnet_id, network['id'], subnet['tenant_id'], name=subnet['name'],
            nw_version=new_network['revision_number'],
            enable_dhcp=subnet['enable_dhcp'], cidr=subnet['cidr'],
            dhcp_ip=mock.ANY, gateway_ip=subnet['gateway_ip'],
            dns_nameservers=subnet['dns_nameservers'],
            host_routes=subnet['host_routes'])

        data = {'subnet': {'name': 'updated'}}
        req = self.new_update_request('subnets', data, subnet_id)
        req.get_response(self.api)
        network = new_network
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.nb_api.update_subnet.assert_called_with(
            subnet_id, network['id'], subnet['tenant_id'], name='updated',
            nw_version=new_network['revision_number'],
            enable_dhcp=subnet['enable_dhcp'], cidr=subnet['cidr'],
            dhcp_ip=mock.ANY, gateway_ip=subnet['gateway_ip'],
            dns_nameservers=subnet['dns_nameservers'],
            host_routes=subnet['host_routes'])

        network = new_network
        req = self.new_delete_request('subnets', subnet_id)
        req.get_response(self.api)
        network = new_network
        new_network = self.driver.get_network(self.context, network['id'])
        self.assertGreater(new_network['revision_number'],
                           network['revision_number'])
        self.nb_api.delete_subnet.assert_called_with(
            subnet_id, network['id'], subnet['tenant_id'],
            nw_version=new_network['revision_number'])

    def test_create_update_port_revision(self):
        with self.port(name='port', device_owner='fake_owner',
                       device_id='fake_id') as p:
            port = p['port']
            self.assertGreater(port['revision_number'], 0)
            self.nb_api.create_lport.assert_called_with(
                id=port['id'],
                lswitch_id=port['network_id'],
                topic=port['tenant_id'],
                macs=[port['mac_address']], ips=mock.ANY,
                subnets=mock.ANY, name=port['name'],
                enabled=port['admin_state_up'],
                chassis=mock.ANY, tunnel_key=mock.ANY,
                version=port['revision_number'],
                device_owner=port['device_owner'],
                device_id=port['device_id'],
                security_groups=mock.ANY,
                port_security_enabled=mock.ANY,
                remote_vtep=False,
                allowed_address_pairs=mock.ANY,
                binding_profile=mock.ANY,
                binding_vnic_type=mock.ANY)

            data = {'port': {'name': 'updated'}}
            req = self.new_update_request('ports', data, port['id'])
            req.get_response(self.api)
            prev_version = port['revision_number']
            port = self.driver.get_lport(self.context, port['id'])
            self.assertGreater(port['revision_number'], prev_version)
            self.nb_api.update_lport.assert_called_with(
                id=port['id'],
                topic=port['tenant_id'],
                macs=[port['mac_address']], ips=mock.ANY,
                subnets=mock.ANY, name=port['name'],
                enabled=port['admin_state_up'],
                chassis=mock.ANY,
                version=port['revision_number'],
                device_owner=port['device_owner'],
                device_id=port['device_id'],
                remote_vtep=False,
                security_groups=mock.ANY,
                port_security_enabled=mock.ANY,
                allowed_address_pairs=mock.ANY,
                binding_profile=mock.ANY,
                binding_vnic_type=mock.ANY)

    def test_delete_network(self):
        network = self._test_create_network_revision()
        req = self.new_delete_request('networks', network['id'])
        req.get_response(self.api)
        self.nb_api.delete_lswitch.assert_called_with(
            id=network['id'], topic=network['tenant_id'])

    def test_create_update_remote_port(self):
        profile = {"port_key": "remote_port", "host_ip": "20.0.0.2"}
        profile_arg = {'binding:profile': profile}
        with self.port(arg_list=('binding:profile',),
                       **profile_arg) as port:
            port = port['port']
            self.nb_api.create_lport.assert_called_with(
                id=port['id'],
                lswitch_id=port['network_id'],
                topic=port['tenant_id'],
                macs=[port['mac_address']], ips=mock.ANY,
                subnets=mock.ANY, name=mock.ANY,
                enabled=port['admin_state_up'],
                chassis="20.0.0.2", tunnel_key=mock.ANY,
                version=port['revision_number'],
                device_owner=port['device_owner'],
                device_id=port['device_id'],
                security_groups=mock.ANY,
                port_security_enabled=mock.ANY,
                remote_vtep=True,
                allowed_address_pairs=mock.ANY,
                binding_profile=profile,
                binding_vnic_type=mock.ANY)

            profile['host_ip'] = "20.0.0.20"
            data = {'port': {'binding:profile': profile}}
            req = self.new_update_request('ports', data, port['id'])
            req.get_response(self.api)
            self.nb_api.update_lport.assert_called_with(
                id=port['id'],
                topic=port['tenant_id'],
                macs=[port['mac_address']], ips=mock.ANY,
                subnets=mock.ANY, name=mock.ANY,
                enabled=port['admin_state_up'],
                chassis="20.0.0.20",
                version=mock.ANY,
                device_owner=port['device_owner'],
                device_id=port['device_id'],
                remote_vtep=True,
                security_groups=mock.ANY,
                port_security_enabled=mock.ANY,
                allowed_address_pairs=mock.ANY,
                binding_profile=profile,
                binding_vnic_type=mock.ANY)

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
