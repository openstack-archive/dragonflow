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

from dragonflow.common import constants
from dragonflow import conf as cfg
from dragonflow.db.models import ovs
from dragonflow.tests.common import constants as const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestOvsdbMonitor(test_base.DFTestBase):
    def setUp(self):
        super(TestOvsdbMonitor, self).setUp()
        self.set_wanted_vms = set()

    def _check_wanted_vm_online(self, update, mac):
        if update.table != ovs.OvsPort.table_name:
            return False
        if update.action != "create" and update.action != "set":
            return False
        if update.value is None:
            return False

        _interface = ovs.OvsPort.from_json(update.value)
        if str(_interface.attached_mac) != mac:
            return False
        elif _interface.type != constants.OVS_VM_INTERFACE:
            return False
        elif _interface.lport is None:
            return False
        elif _interface.ofport <= 0:
            return False
        elif _interface.admin_state != "up":
            return False
        else:
            return True

    def _check_wanted_vm_offline(self, update, mac):
        if update.table != ovs.OvsPort.table_name:
            return False
        if update.action != "delete":
            return False
        _interface = ovs.OvsPort.from_json(update.value)
        if _interface is None:
            return False
        elif str(_interface.attached_mac) != mac:
            return False
        elif _interface.type != constants.OVS_VM_INTERFACE:
            return False
        elif _interface.lport is None:
            return False
        else:
            return True

    def _get_wanted_vm_online(self, mac):
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self._check_wanted_vm_online(self.next_update, mac):
                return True
        return False

    def _get_wanted_vm_offline(self, mac):
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self._check_wanted_vm_offline(self.next_update, mac):
                return True
        return False

    def _get_all_wanted_vms_online(self, mac1, mac2):
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self._check_wanted_vm_online(self.next_update, mac1):
                self.set_wanted_vms.add(mac1)
                if len(self.set_wanted_vms) == 2:
                    return True
            elif self._check_wanted_vm_online(self.next_update, mac2):
                self.set_wanted_vms.add(mac2)
                if len(self.set_wanted_vms) == 2:
                    return True
            else:
                continue
        return False

    def test_notify_message(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = self.store(objects.SubnetTestObj(self.neutron, self.nb_api,
                                                  network_id))
        subnet_body = {'network_id': network_id,
                       'cidr': '10.10.0.0/24',
                       'gateway_ip': '10.10.0.1',
                       'ip_version': 4,
                       'name': 'private',
                       'enable_dhcp': True}
        subnet.create(subnet=subnet_body)
        self.assertTrue(network.exists())
        self.assertTrue(subnet.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        self.assertIsNotNone(vm.server.addresses['mynetwork'])
        mac = vm.server.addresses['mynetwork'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        # wait util get the message we want
        utils.wait_until_true(
            lambda: self._get_wanted_vm_online(mac),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Could not get wanted online vm')
        )

        # wait util get the message we want
        vm.close()
        utils.wait_until_true(
            lambda: self._get_wanted_vm_offline(mac),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Could not get wanted offline vm')
        )
        utils.wait_until_none(
            lambda: utils.find_logical_port(self.nb_api, ip=None, mac=mac),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Port was not deleted')
        )

    def test_reply_message(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = self.store(objects.SubnetTestObj(self.neutron, self.nb_api,
                                                  network_id))
        subnet_body = {'network_id': network_id,
                       'cidr': '10.20.0.0/24',
                       'gateway_ip': '10.20.0.1',
                       'ip_version': 4,
                       'name': 'private',
                       'enable_dhcp': True}
        subnet.create(subnet=subnet_body)
        self.assertTrue(network.exists())
        self.assertTrue(subnet.exists())

        vm1 = self.store(objects.VMTestObj(self, self.neutron))
        vm1.create(network=network)
        self.assertIsNotNone(vm1.server.addresses['mynetwork'])
        mac1 = vm1.server.addresses['mynetwork'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac1)

        vm2 = self.store(objects.VMTestObj(self, self.neutron))
        vm2.create(network=network)
        self.assertIsNotNone(vm2.server.addresses['mynetwork'])
        mac2 = vm2.server.addresses['mynetwork'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac2)

        # wait util get the message we want
        self.set_wanted_vms.clear()
        utils.wait_until_true(
            lambda: self._get_all_wanted_vms_online(mac1, mac2),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Could not get wanted online vm')
        )
        vm1.close()
        vm2.close()
        utils.wait_until_none(
            lambda: utils.find_logical_port(self.nb_api, ip=None, mac=mac1),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Port was not deleted')
        )
        utils.wait_until_none(
            lambda: utils.find_logical_port(self.nb_api, ip=None, mac=mac2),
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT, sleep=1,
            exception=Exception('Port was not deleted')
        )

    def test_virtual_tunnel_port(self):
        expected_tunnel_types = cfg.CONF.df.tunnel_types

        tunnel_ports = self.vswitch_api.get_virtual_tunnel_ports()
        self.assertEqual(len(expected_tunnel_types), len(tunnel_ports))
        tunnel_types = set()
        for t in tunnel_ports:
            self.assertEqual(t.tunnel_type + "-vtp",
                             t.name)
            tunnel_types.add(t.tunnel_type)

        self.assertEqual(set(expected_tunnel_types), tunnel_types)
