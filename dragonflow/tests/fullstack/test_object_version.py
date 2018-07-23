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

import contextlib

from oslo_concurrency import lockutils

from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.db.models import qos
from dragonflow.db.models import secgroups
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestObjectVersion(test_base.DFTestBase):

    def setUp(self):
        super(TestObjectVersion, self).setUp()

    def test_network_version(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        lean_lswitch = l2.LogicalSwitch(id=network_id)
        self.assertTrue(network.exists())
        version = self.nb_api.get(lean_lswitch).version

        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet.create()
        self.assertTrue(subnet.exists())
        new_version = self.nb_api.get(lean_lswitch).version
        self.assertGreater(new_version, version)

        subnet.close()
        self.assertFalse(subnet.exists())
        version = new_version
        new_version = self.nb_api.get(lean_lswitch).version
        self.assertGreater(new_version, version)

        network.close()
        self.assertFalse(network.exists())

    def test_port_version(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())

        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet.create()
        self.assertTrue(subnet.exists())

        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        port_id = port.create()
        self.assertTrue(port.exists())
        prev_version = self.nb_api.get(l2.LogicalPort(id=port_id)).version

        port.update()
        self.assertTrue(port.exists())
        version = self.nb_api.get(l2.LogicalPort(id=port_id)).version
        self.assertGreater(version, prev_version)

        port.close()
        self.assertFalse(port.exists())
        subnet.close()
        self.assertFalse(subnet.exists())
        network.close()
        self.assertFalse(network.exists())

    def test_router_version(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet_id = subnet.create()
        self.assertTrue(subnet.exists())
        router = objects.RouterTestObj(self.neutron, self.nb_api)
        self.addCleanup(router.close)
        router_id = router.create()
        self.assertTrue(router.exists())
        prev_version = self.nb_api.get(l3.LogicalRouter(id=router_id)).version

        subnet_msg = {'subnet_id': subnet_id}
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        version = self.nb_api.get(l3.LogicalRouter(id=router_id)).version
        self.assertGreater(version, prev_version)
        prev_version = version

        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        version = self.nb_api.get(l3.LogicalRouter(id=router_id)).version
        self.assertGreater(version, prev_version)

        router.close()
        self.assertFalse(router.exists())
        subnet.close()
        self.assertFalse(subnet.exists())
        network.close()
        self.assertFalse(network.exists())

    def test_sg_version(self):
        secgroup = objects.SecGroupTestObj(self.neutron, self.nb_api)
        self.addCleanup(secgroup.close)
        sg_id = secgroup.create()
        self.assertTrue(secgroup.exists())
        sg_obj = secgroups.SecurityGroup(id=sg_id)
        version = self.nb_api.get(sg_obj).version

        secrule_id = secgroup.rule_create()
        self.assertTrue(secgroup.rule_exists(secrule_id))
        sg_obj = secgroups.SecurityGroup(id=sg_id)
        new_version = self.nb_api.get(sg_obj).version
        self.assertGreater(new_version, version)

        secgroup.rule_delete(secrule_id)
        self.assertFalse(secgroup.rule_exists(secrule_id))
        version = new_version
        sg_obj = secgroups.SecurityGroup(id=sg_id)
        new_version = self.nb_api.get(sg_obj).version
        self.assertGreater(new_version, version)

        secgroup.close()
        self.assertFalse(secgroup.exists())

    def test_qospolicy_version(self):
        qospolicy = objects.QosPolicyTestObj(self.neutron, self.nb_api)
        self.addCleanup(qospolicy.close)
        policy_id = qospolicy.create()
        self.assertTrue(qospolicy.exists())
        version = self.nb_api.get(qos.QosPolicy(id=policy_id)).version

        rule = {'max_kbps': '1000', 'max_burst_kbps': '100'}
        qospolicy.create_rule(policy_id, rule, 'bandwidth_limit')
        self.assertTrue(qospolicy.exists())
        new_version = self.nb_api.get(qos.QosPolicy(id=policy_id)).version
        self.assertGreater(new_version, version)

        qospolicy.close()
        self.assertFalse(qospolicy.exists())

    @contextlib.contextmanager
    def _prepare_ext_net(self):
        external_net = objects.find_first_network(self.neutron,
                                                  {'router:external': True})
        if not external_net:
            network = objects.NetworkTestObj(self.neutron, self.nb_api)
            self.addCleanup(network.close)
            external_net_para = {'name': 'public', 'router:external': True}
            external_network_id = network.create(network=external_net_para)
            self.assertTrue(network.exists())
            ext_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                               external_network_id)
            self.addCleanup(ext_subnet.close)
            external_subnet_para = {'cidr': '192.168.199.0/24',
                                    'ip_version': 4,
                                    'network_id': external_network_id}
            ext_subnet.create(external_subnet_para)
            self.assertTrue(ext_subnet.exists())
        else:
            external_network_id = external_net['id']
        self.assertIsNotNone(external_network_id)

        # return external network
        yield external_network_id

        if not external_net:
            ext_subnet.close()
            self.assertFalse(ext_subnet.exists())
            network.close()
            self.assertFalse(network.exists())

    @lockutils.synchronized('need-external-net')
    def test_floatingip_version(self):
        with self._prepare_ext_net() as external_network_id:
            private_network = objects.NetworkTestObj(self.neutron, self.nb_api)
            self.addCleanup(private_network.close)
            private_network_id = private_network.create()
            self.assertTrue(private_network.exists())
            priv_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                                private_network_id)
            self.addCleanup(priv_subnet.close)
            router = objects.RouterTestObj(self.neutron, self.nb_api)
            self.addCleanup(router.close)
            port = objects.PortTestObj(self.neutron,
                                       self.nb_api, private_network_id)
            self.addCleanup(port.close)
            fip = objects.FloatingipTestObj(self.neutron, self.nb_api)
            self.addCleanup(fip.close)

            router_para = {
                'name': 'myrouter1', 'admin_state_up': True,
                'external_gateway_info': {"network_id": external_network_id}}
            router.create(router=router_para)
            self.assertTrue(router.exists())

            private_subnet_para = {'cidr': '10.0.0.0/24',
                                   'ip_version': 4,
                                   'network_id': private_network_id}
            priv_subnet_id = priv_subnet.create(private_subnet_para)
            self.assertTrue(priv_subnet.exists())
            router_interface = router.add_interface(subnet_id=priv_subnet_id)
            router_lport = self.nb_api.get(
                l2.LogicalPort(id=router_interface['port_id']))
            self.assertIsNotNone(router_lport)

            port_id = port.create()
            self.assertIsNotNone(port.get_logical_port())

            fip_para = {'floating_network_id': external_network_id}
            # create
            fip.create(fip_para)
            self.assertTrue(fip.exists())
            prev_version = fip.get_floatingip().version

            # associate with port
            fip.update({'port_id': port_id})
            fip_obj = fip.get_floatingip()
            self.assertEqual(fip_obj.lport.id, port_id)
            version = fip_obj.version
            self.assertGreater(version, prev_version)
            prev_version = version

            fip.update({})
            fip_obj = fip.get_floatingip()
            self.assertIsNone(fip_obj.lport)
            version = fip_obj.version
            self.assertGreater(version, prev_version)

            fip.close()
            self.assertFalse(fip.exists())
            port.close()
            self.assertFalse(port.exists())
            router.close()
            self.assertFalse(router.exists())
            priv_subnet.close()
            self.assertFalse(priv_subnet.exists())
