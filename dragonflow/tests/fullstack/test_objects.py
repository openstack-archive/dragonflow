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


class SecGroupTestWrapper(object):

    def __init__(self, neutron, nb_api):
        self.secgroup_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.deleted = False

    def create(self, secgroup={'name': 'mysecgroup1'}):
        new_secgroup = self.neutron.create_security_group({'security_group':
                                                           secgroup})
        self.secgroup_id = new_secgroup['security_group']['id']
        return self.secgroup_id

    def __del__(self):
        if self.deleted or self.secgroup_id is None:
            return
        self.delete()

    def delete(self):
        self.neutron.delete_security_group(self.secgroup_id)
        self.deleted = True

    def exists(self):
        secgroups = self.nb_api.get_secgroups()
        for secgroup in secgroups:
            if secgroup.get_name() == self.secgroup_id:
                return True
        return False

    def rule_create(self, secrule={'ethertype': 'IPv4',
                                   'direction': 'ingress'}):
        secrule['security_group_id'] = self.secgroup_id
        new_secrule = self.neutron.create_security_group_rule(
                        {'security_group_rule': secrule})
        return new_secrule['security_group_rule']['id']

    def rule_delete(self, secrule_id):
        self.neutron.delete_security_group_rule(secrule_id)

    def rule_exists(self, secrule_id):
        secgroups = self.nb_api.get_secgroups()
        for secgroup in secgroups:
            if secgroup.get_name() == self.secgroup_id:
                for rule in secgroup.get_rules():
                    if rule.get_id() == secrule_id:
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
