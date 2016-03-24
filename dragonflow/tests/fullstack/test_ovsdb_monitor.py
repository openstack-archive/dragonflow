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

from dragonflow.db.drivers.ovsdb_vswitch_impl import OvsdbMonitor
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestOvsdbMonitor(test_base.DFTestBase):
    def setUp(self):
        super(TestOvsdbMonitor, self).setUp()
        self.ovsdb_monitor = OvsdbMonitor("127.0.0.1", "6640", self.nb_api)
        self.ovsdb_monitor.daemonize()

    def tearDown(self):
        super(TestOvsdbMonitor, self).tearDown()
        self.ovsdb_monitor.stop()

    def queue_has_data(self, queue):
        if queue.qsize() > 0:
            return True
        else:
            return False

    def check_wanted_vm_online(self, update, mac):
        if update.table != "ovsinterface":
            return False
        if update.action != "create":
            return False
        _interface = update.value
        if _interface is None:
            return False
        elif _interface.get_attached_mac() != mac:
            return False
        elif _interface.get_type() != "vm":
            return False
        elif _interface.get_iface_id() is None:
            return False
        elif _interface.get_ofport() <= 0:
            return False
        elif _interface.get_admin_state() != "up":
            return False
        else:
            return True

    def check_wanted_vm_offline(self, update, mac):
        if update.table != "ovsinterface":
            return False
        if update.action != "delete":
            return False
        _interface = update.value
        if _interface is None:
            return False
        elif _interface.get_attached_mac() != mac:
            return False
        elif _interface.get_type() != "vm":
            return False
        elif _interface.get_iface_id() is None:
            return False
        else:
            return True

    def get_vm_port_by_mac_address(self, mac):
        lports = self.nb_api.get_all_logical_ports()
        for lport in lports:
            if lport.get_mac() == mac:
                return lport
        return None

    def get_wanted_vm_online(self, mac):
        find_wanted_online_vm = False
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self.check_wanted_vm_online(self.next_update, mac):
                find_wanted_online_vm = True
                break
        if find_wanted_online_vm:
            return None
        else:
            return mac

    def get_wanted_vm_offline(self, mac):
        find_wanted_offline_vm = False
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self.check_wanted_vm_offline(self.next_update, mac):
                find_wanted_offline_vm = True
                break
        if find_wanted_offline_vm:
            return None
        else:
            return mac

    def get_all_wanted_vms_online(self, mac1, mac2):
        find_wanted_vm1 = False
        find_wanted_vm2 = False
        while self.nb_api._queue.qsize() > 0:
            self.next_update = self.nb_api._queue.get()
            if self.check_wanted_vm_online(self.next_update, mac1):
                find_wanted_vm1 = True
                if find_wanted_vm1 and find_wanted_vm2:
                    break
            elif self.check_wanted_vm_online(self.next_update, mac2):
                find_wanted_vm2 = True
                if find_wanted_vm1 and find_wanted_vm2:
                    break
            else:
                continue
        if find_wanted_vm1 and find_wanted_vm2:
            return None
        else:
            return mac1

    def test_notify_message(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
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
        self.assertIsNotNone(vm.server.addresses['private'])
        mac = vm.server.addresses['private'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        #wait util get the message we want
        utils.wait_until_none(
            lambda: self.get_wanted_vm_online(mac), timeout=30, sleep=1,
            exception=Exception('Could not get wanted online vm')
        )

        #wait util get the message we want
        vm.close()
        utils.wait_until_none(
            lambda: self.get_wanted_vm_offline(mac), timeout=30, sleep=1,
            exception=Exception('Could not get wanted offline vm')
        )
        utils.wait_until_none(
            lambda: self.get_vm_port_by_mac_address(mac), timeout=30, sleep=1,
            exception=Exception('Port was not deleted')
        )

    def test_reply_message(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
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
        self.assertIsNotNone(vm1.server.addresses['private'])
        mac1 = vm1.server.addresses['private'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac1)

        vm2 = self.store(objects.VMTestObj(self, self.neutron))
        vm2.create(network=network)
        self.assertIsNotNone(vm2.server.addresses['private'])
        mac2 = vm2.server.addresses['private'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac2)

        #wait util get the message we want
        utils.wait_until_none(
            lambda: self.get_all_wanted_vms_online(mac1, mac2), timeout=30, sleep=1,
            exception=Exception('Could not get wanted online vm')
        )
        vm1.close()
        vm2.close()
        utils.wait_until_none(
            lambda: self.get_vm_port_by_mac_address(mac1), timeout=30, sleep=1,
            exception=Exception('Port was not deleted')
        )
        utils.wait_until_none(
            lambda: self.get_vm_port_by_mac_address(mac2), timeout=30, sleep=1,
            exception=Exception('Port was not deleted')
        )
