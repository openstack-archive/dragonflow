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


class RouterTestWrapper(object):

    def __init__(self, neutron, nb_api):
        self.router_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.deleted = False

    def create(self, router={'name': 'myrouter1', 'admin_state_up': True}):
        new_router = self.neutron.create_router({'router': router})
        self.router_id = new_router['router']['id']
        return self.router_id

    def __del__(self):
        if self.deleted or self.router_id is None:
            return
        self.delete()

    def delete(self):
        ports = self.neutron.list_ports(device_id=self.router_id)
        ports = ports['ports']
        for port in ports:
            if port['device_owner'] == 'network:router_interface':
                for fip in port['fixed_ips']:
                    subnet_msg = {'subnet_id': fip['subnet_id']}
                    self.neutron.remove_interface_router(
                         self.router_id, body=subnet_msg)
            else:
                self.neutron.delete_port(port['id'])
        self.neutron.delete_router(self.router_id)
        self.deleted = True

    def exists(self):
        routers = self.nb_api.get_routers()
        for router in routers:
            if router.get_name() == self.router_id:
                return True
        return False


class NetworkTestWrapper(object):

    def __init__(self, neutron, nb_api):
        self.network_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.deleted = False

    def create(self, network={'name': 'mynetwork1', 'admin_state_up': True}):
        network = self.neutron.create_network({'network': network})
        self.network_id = network['network']['id']
        return self.network_id

    def __del__(self):
        if self.deleted or self.network_id is None:
            return
        self.delete()

    def delete(self):
        self.neutron.delete_network(self.network_id)
        self.deleted = True

    def exists(self):
        network = self.nb_api.get_lswitch(self.network_id)
        if network:
            return True
        return False


class VMTestWrapper(object):

    def __init__(self, parent):
        self.server_id = None
        self.server = None
        self.deleted = False
        self.parent = parent
        creds = test_base.credentials()
        auth_url = creds['auth_url'] + "/v2.0"
        self.nova = novaclient.Client('2', creds['username'],
                        creds['password'], 'demo', auth_url)

    def create(self, script=None):
        image = self.nova.images.find(name="cirros-0.3.4-x86_64-uec")
        self.parent.assertIsNotNone(image)
        flavor = self.nova.flavors.find(name="m1.tiny")
        self.parent.assertIsNotNone(flavor)
        network = self.nova.networks.find(label='private')
        self.parent.assertIsNotNone(network)
        nics = [{'net-id': network.id}]
        if script:
            self.server = self.nova.servers.create(name='test', image=image.id,
                              flavor=flavor.id, nics=nics, user_data=script)
        else:
            self.server = self.nova.servers.create(name='test', image=image.id,
                              flavor=flavor.id, nics=nics)
        self.parent.assertIsNotNone(self.server)
        self.server_id = self.server.id
        mmax = 30
        while mmax > 0:
            time.sleep(1)
            server2 = self.nova.servers.find(id=self.server_id)
            if server2.status == 'ACTIVE':
                break
            else:
                mmax = mmax - 1
        if max == 0:
            self.parent.assertNotEqual('vm_status', server2.status)
        return self.server_id

    def __del__(self):
        if self.deleted or self.server_id is None:
            return
        self.delete()

    def delete(self):
        self.nova.servers.delete(self.server)
        self.deleted = True

   def exists(self):
        if self.server_id is None:
            return False
        self.server = self.nova.servers.find(id=self.server_id)
        if self.server is None:
            return False
        return True

    def dump(self):
        return self.nova.servers.get_console_output(self.server)

