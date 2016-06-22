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

import six


class stub_wrap_db_lock(object):
    def __init__(self, type):
        pass

    def __call__(self, f):
        @six.wraps(f)
        def stub_wrap_db_lock(*args, **kwargs):
            f(*args, **kwargs)
        return stub_wrap_db_lock


import mock

# mock.patch must before import mech_driver, because mech_driver will load the
# lockedobjects_db
mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
           stub_wrap_db_lock).start()
from dragonflow.db.neutron import versionobjects_db as version_db
from dragonflow.neutron.ml2 import mech_driver
from neutron.db import securitygroups_db
from neutron import manager
from neutron.tests import base


class TestDFMechDriver(base.BaseTestCase):

    """Testing dragonflow mechanism driver."""

    def setUp(self):
        super(TestDFMechDriver, self).setUp()
        self.driver = mech_driver.DFMechDriver()
        self.driver.initialize()
        self.driver.nb_api = mock.Mock()
        self.dbversion = 0
        version_db._create_db_version_row = mock.Mock(
            return_value=self.dbversion)
        version_db._update_db_version_row = mock.Mock(
            return_value=self.dbversion)
        version_db._delete_db_version_row = mock.Mock()

    def test_create_network_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        network_type = 'vxlan'
        segmentation_id = 456

        network_context = self._get_network_context(tenant_id,
                                                    network_id,
                                                    network_type,
                                                    segmentation_id)

        self.driver.create_network_postcommit(network_context)
        self.driver.nb_api.create_lswitch.assert_called_with(
            id=network_id,
            name='FakeNetwork',
            topic=tenant_id,
            network_type=network_type,
            router_external=False,
            segmentation_id=segmentation_id,
            subnets=[],
            mtu=1450,
            version=self.dbversion)

    def test_delete_network_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        network_type = 'vxlan'
        segmentation_id = 456

        self.driver.nb_api.get_all_logical_ports = mock.Mock(return_value=[])
        network_context = self._get_network_context(tenant_id,
                                                    network_id,
                                                    network_type,
                                                    segmentation_id)

        self.driver.delete_network_postcommit(network_context)
        self.driver.nb_api.delete_lswitch.assert_called_with(
            id=network_id, topic=tenant_id)

    def test_create_subnet_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        subnet_id = '122'
        cidr = '192.0.0.0/8'
        gateway_ip = '192.0.0.1'
        dhcp_ip = '1.1.1.1'
        enable_dhcp = True
        dns_nameservers = '2.2.2.2'
        port = {'fixed_ips': [{'subnet_id': subnet_id, 'ip_address': dhcp_ip}]}

        self.driver._handle_create_subnet_dhcp = mock.Mock(
            return_value=port)
        subnet_context = self._get_subnet_context(tenant_id, network_id,
                                                  subnet_id, cidr, gateway_ip,
                                                  enable_dhcp, dns_nameservers)

        self.driver.create_subnet_postcommit(subnet_context)
        self.driver.nb_api.add_subnet.assert_called_with(
            subnet_id, network_id, tenant_id, enable_dhcp=enable_dhcp,
            cidr=cidr, dhcp_ip=dhcp_ip, gateway_ip=gateway_ip,
            dns_nameservers=dns_nameservers, name='FakeSubnet',
            host_routes=[],
            nw_version=self.dbversion)

    def test_update_subnet_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        subnet_id = '122'
        cidr = '192.0.0.0/8'
        gateway_ip = '192.0.0.100'
        dhcp_ip = '1.1.1.1'
        enable_dhcp = True
        dns_nameservers = '2.2.2.2'
        port = {'fixed_ips': [{'subnet_id': subnet_id, 'ip_address': dhcp_ip}]}

        self.driver._handle_update_subnet_dhcp = mock.Mock(
            return_value=port)
        subnet_context = self._get_subnet_context(tenant_id, network_id,
                                                  subnet_id, cidr, gateway_ip,
                                                  enable_dhcp, dns_nameservers)

        self.driver.update_subnet_postcommit(subnet_context)
        self.driver.nb_api.update_subnet.assert_called_with(
            subnet_id, network_id, tenant_id, enable_dhcp=enable_dhcp,
            cidr=cidr, dhcp_ip=dhcp_ip, gateway_ip=gateway_ip,
            dns_nameservers=dns_nameservers, name='FakeSubnet',
            host_routes=[],
            nw_version=self.dbversion)

    def test_delete_subnet_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        subnet_id = '122'
        cidr = '192.0.0.0/8'
        gateway_ip = '192.0.0.1'
        enable_dhcp = True
        dns_nameservers = '2.2.2.2'

        subnet_context = self._get_subnet_context(tenant_id, network_id,
                                                  subnet_id, cidr, gateway_ip,
                                                  enable_dhcp, dns_nameservers)

        self.driver.delete_subnet_postcommit(subnet_context)
        self.driver.nb_api.delete_subnet.assert_called_with(
            subnet_id, network_id, tenant_id, nw_version=self.dbversion)

    def test_create_port_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        port_id = '453'
        fips = [{"subnet_id": "sub-1", "ip_address": "10.0.0.1"}]
        allowed_macs = 'ff:ff:ff:ff:ff:ff'
        tunnel_key = '9999'

        securitygroups_db.SecurityGroupDbMixin._get_security_groups_on_port = \
            mock.Mock(return_value=None)
        self.driver._get_allowed_mac_addresses_from_port = mock.Mock(
            return_value=allowed_macs)
        self.driver.nb_api.allocate_tunnel_key = mock.Mock(
            return_value=tunnel_key)
        port_context = self._get_port_context(tenant_id, network_id, port_id,
                                              fips)

        self.driver.create_port_postcommit(port_context)
        self.driver.nb_api.create_lport.assert_called_with(
            id=port_id, lswitch_id=network_id, topic=tenant_id,
            macs=['aabb'], ips=['10.0.0.1'],
            name='FakePort', subnets=['sub-1'],
            enabled=True, chassis=None, tunnel_key=tunnel_key,
            device_owner='compute',
            port_security_enabled=False, security_groups=None,
            allowed_address_pairs=None, version=self.dbversion)

    def test_update_port_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        port_id = '453'
        fips = [{"subnet_id": "sub-1", "ip_address": "10.0.0.1"}]
        tunnel_key = '9999'

        securitygroups_db.SecurityGroupDbMixin._get_security_groups_on_port = \
            mock.Mock(return_value=None)

        self.driver.nb_api.allocate_tunnel_key = mock.Mock(
            return_value=tunnel_key)
        port_context = self._get_port_context(tenant_id, network_id, port_id,
                                              fips)

        self.driver.update_port_postcommit(port_context)
        self.driver.nb_api.update_lport.assert_called_with(
            id=port_id, name='FakePort', topic=tenant_id,
            macs=['aabb'], ips=['10.0.0.1'],
            subnets=['sub-1'],
            enabled=True, chassis=None, port_security_enabled=False,
            allowed_address_pairs=None, security_groups=None,
            device_owner='compute', version=self.dbversion)

    def test_delete_port_postcommit(self):
        tenant_id = 'test'
        network_id = '123'
        port_id = '453'
        fips = [{"subnet_id": "sub-1", "ip_address": "10.0.0.1"}]

        port_context = self._get_port_context(tenant_id, network_id, port_id,
                                              fips)

        self.driver.delete_port_postcommit(port_context)
        self.driver.nb_api.delete_lport.assert_called_with(
            id=port_id, topic=tenant_id)

    def test_create_security_group(self):
        tenant_id = 'test'
        sg_id = '123'
        sg_name = 'FakeSecurityGroup'
        rules = [{'direction': 'egress',
                  'protocol': None,
                  'description': '',
                  'port_range_max': None,
                  'id': 'fc17c61e-7634-47f6-b01c-7ea4d73a7ac6',
                  'remote_group_id': None, 'remote_ip_prefix': None,
                  'security_group_id': sg_id,
                  'tenant_id': tenant_id,
                  'port_range_min': None, 'ethertype': 'IPv4'}]

        kwargs = self._get_security_group_kwargs(tenant_id, sg_id,
                                                 sg_name, rules)
        resource = 'security_group'
        event = 'after_create'
        trigger = '0xffffffff'

        self.driver.create_security_group(resource, event, trigger, **kwargs)
        self.driver.nb_api.create_security_group.assert_called_with(
            id=sg_id, name=sg_name, topic=tenant_id, rules=rules,
            version=self.dbversion)

    def test_delete_security_group(self):
        tenant_id = 'test'
        sg_id = '123'
        sg_name = 'FakeSecurityGroup'
        rules = [{'direction': 'egress',
                  'protocol': None,
                  'description': '',
                  'port_range_max': None,
                  'id': 'fc17c61e-7634-47f6-b01c-7ea4d73a7ac6',
                  'remote_group_id': None, 'remote_ip_prefix': '0.0.0.0/0',
                  'security_group_id': sg_id,
                  'tenant_id': tenant_id,
                  'port_range_min': None, 'ethertype': 'IPv4'}]

        kwargs = self._get_security_group_kwargs(tenant_id, sg_id,
                                                 sg_name, rules)
        resource = 'security_group'
        event = 'before_delete'
        trigger = '0xffffffff'

        self.driver.delete_security_group(resource, event, trigger, **kwargs)
        self.driver.nb_api.delete_security_group.assert_called_with(
            sg_id, topic=tenant_id)

    def test_create_security_group_rule(self):
        tenant_id = 'test'
        sg_id = '123'
        rule = {'direction': u'ingress',
                'protocol': u'tcp',
                'description': '',
                'port_range_max': 2121,
                'id': '88b804a3-661b-40bc-b078-6156374ba355',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'security_group_id': sg_id,
                'tenant_id': tenant_id,
                'port_range_min': 2121,
                'ethertype': 'IPv4'}

        kwargs = self._get_security_group_rule_kwargs(rule, None, fakecontext)
        resource = 'security_group_rule'
        event = 'after_create'
        trigger = '0xffffffff'

        self.driver.create_security_group_rule(resource, event,
                                               trigger, **kwargs)
        self.driver.nb_api.add_security_group_rules.assert_called_with(
            sg_id, tenant_id, sg_rules=[rule], sg_version=self.dbversion)

    def test_delete_security_group_rule(self):
        tenant_id = 'test'
        sg_id = '123'
        sgr_id = '456'
        rule = {'direction': u'ingress',
                'protocol': u'tcp',
                'description': '',
                'port_range_max': 2121,
                'id': '88b804a3-661b-40bc-b078-6156374ba355',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'security_group_id': sg_id,
                'tenant_id': tenant_id,
                'port_range_min': 2121,
                'ethertype': 'IPv4'}

        manager.NeutronManager.get_plugin = mock.Mock(return_value=core_plugin)

        context = FakeSecurityGroupRuleContext(tenant_id)
        kwargs = self._get_security_group_rule_kwargs(rule, sgr_id, context)

        resource = 'security_group_rule'
        event = 'before_delete'
        trigger = '0xffffffff'

        self.driver.delete_security_group_rule(resource, event,
                                               trigger, **kwargs)
        self.driver.nb_api.delete_security_group_rule.assert_called_with(
            sg_id, sgr_id, tenant_id, sg_version=self.dbversion)

    def _get_subnet_context(self, tenant_id, net_id, subnet_id, cidr,
                            gateway_ip, enable_dhcp, dns_nameservers):
        # sample data for testing purpose only.
        subnet = {'tenant_id': tenant_id,
                  'network_id': net_id,
                  'id': subnet_id,
                  'cidr': cidr,
                  'name': 'FakeSubnet',
                  'ip_version': 4,
                  'gateway_ip': gateway_ip,
                  'enable_dhcp': enable_dhcp,
                  'dns_nameservers': dns_nameservers,
                  'db_version': self.dbversion}
        return FakeContext(subnet)

    def _get_port_context(self, tenant_id, net_id, port_id, fixed_ips):
        # sample data for testing purpose only.
        port = {'device_id': '1234',
                'name': 'FakePort',
                'mac_address': 'aabb',
                'device_owner': 'compute',
                'tenant_id': tenant_id,
                'id': port_id,
                'fixed_ips': fixed_ips,
                'admin_state_up': True,
                'status': 'ACTIVE',
                'network_id': net_id,
                'db_version': self.dbversion}
        return FakeContext(port)

    def _get_network_context(self, tenant_id, net_id, network_type, seg_id):
        # sample data for testing purpose only.
        network = {'id': net_id,
                   'tenant_id': tenant_id,
                   'admin_state_up': True,
                   'status': 'ACTIVE',
                   'name': 'FakeNetwork',
                   'provider:network_type': network_type,
                   'provider:segmentation_id': seg_id,
                   'router:external': False,
                   'mtu': 1450,
                   'db_version': self.dbversion}
        segments = [{'segmentation_id': seg_id}]
        return FakeNetworkContext(network, segments)

    def _get_security_group_kwargs(self, tenant_id, sg_id, sg_name, rules):
        kwargs = {'security_group':
                  {'tenant_id': tenant_id,
                   'id': sg_id,
                   'security_group_rules': rules,
                   'security_group_id': sg_id,
                   'name': sg_name},
                  'security_group_id': sg_id,
                  'context': fakecontext}
        return kwargs

    def _get_security_group_rule_kwargs(self, rules, sgr_id, context):
        kwargs = {'security_group_rule': rules,
                  'security_group_rule_id': sgr_id,
                  'context': context}
        return kwargs


class FakeNetworkContext(object):
    """To generate network context for testing purposes only."""
    def __init__(self, network, segments):
        self._network = network
        self._segments = segments
        self._plugin_context = fakeplugincontext

    @property
    def current(self):
        return self._network

    @property
    def network_segments(self):
        return self._segments

    def __exit__(self):
        pass


class FakeContext(object):
    """To generate context for testing purposes only."""
    def __init__(self, record):
        self._record = record
        self._plugin_context = fakeplugincontext
        self._session = fakesession

    @property
    def current(self):
        return self._record

    @property
    def original(self):
        return self._record

    @property
    def session(self):
        return self._session


class FakeSecurityGroupRuleContext(object):
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self._session = fakesession

    @property
    def session(self):
        return self._session


class FakePluginContext(object):
    def __init__(self):
        self._session = fakesession

    @property
    def session(self):
        return self._session


class FakeSession(object):
    def __init__(self):
        pass

    def begin(self, subtransactions=True):
        return sessiontransaction


class SessionTransaction(object):
    def __init__(self, session, parent=None, nested=False):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass


class CorePlugin(object):
    def __init__(self):
        pass

    def get_security_group_rule(self, context, sgr_id):
        rule = {'direction': u'ingress',
                'protocol': u'tcp',
                'description': '',
                'port_range_max': 2121,
                'id': '88b804a3-661b-40bc-b078-6156374ba355',
                'remote_group_id': None,
                'remote_ip_prefix': '0.0.0.0/0',
                'security_group_id': '123',
                'tenant_id': 123,
                'port_range_min': 2121,
                'ethertype': 'IPv4'}
        return rule


fakesession = FakeSession()

fakeplugincontext = FakePluginContext()

sessiontransaction = SessionTransaction(fakesession, None, False)

fakecontext = FakeContext('aaa')

core_plugin = CorePlugin()
