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

import time

from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestPortQos(test_base.DFTestBase):
    def test_port_with_qospolicy(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'test_network'})
        self.assertTrue(network.exists())

        subnet = self.store(objects.SubnetTestObj(self.neutron, self.nb_api,
                                                  network_id=network_id))
        subnet.create()
        self.assertTrue(subnet.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm_id = vm.create(network=network)

        ovsdb = utils.OvsDBParser()
        vm_port_id = ovsdb.get_port_id_by_vm_id(vm_id)
        self.assertIsNotNone(vm_port_id)

        qospolicy = self.store(objects.QosPolicyTestObj(self.neutron,
                                                        self.nb_api))
        qos_policy_id = qospolicy.create()
        self.assertTrue(qospolicy.exists())
        qospolicy.update(qos_policy_id,
                         {'max_kbps': '1000', 'max_burst_kbps': '100'},
                         'bandwidth_limit')
        qospolicy.update(qos_policy_id,
                         {'dscp_mark': '10'},
                         'dscp_marking')

        port = self.store(objects.PortTestObj(self.neutron, self.nb_api,
                                              network_id, vm_port_id))
        port_param = {'qos_policy_id': qos_policy_id}
        port.update(port_param)
        self.assertEqual(qos_policy_id, port.get_logical_port().get_qos())

        interface = ovsdb.get_interface_by_port_id(vm_port_id)
        self.assertIsNotNone(interface)
        self.assertEqual('1000', interface.get('ingress_policing_rate'))
        self.assertEqual('100', interface.get('ingress_policing_burst'))

        queue = ovsdb.get_queue_by_port_id(vm_port_id)
        self.assertIsNotNone(queue)
        self.assertEqual(queue['other_config']['max-rate'], '1024000')
        self.assertEqual(queue['other_config']['min-rate'], '1024000')
        self.assertEqual(queue['dscp'], '10')

        qos = ovsdb.get_qos_by_port_id(vm_port_id)
        self.assertIsNotNone(qos)
        self.assertEqual(qos['queues']['0'], queue['_uuid'])

        ovs_port = ovsdb.get_port_by_interface_id(interface.get('_uuid'))
        self.assertIsNotNone(ovs_port)
        self.assertEqual(ovs_port['qos'], qos['_uuid'])

        vm.close()
        time.sleep(utils.DEFAULT_CMD_TIMEOUT)

        queue = ovsdb.get_queue_by_port_id(vm_port_id)
        self.assertIsNone(queue)

        qos = ovsdb.get_qos_by_port_id(vm_port_id)
        self.assertIsNone(qos)