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

import netaddr

import time

from novaclient import client as novaclient

from oslo_log import log

from dragonflow._i18n import _LW
from dragonflow.tests.fullstack import test_base

LOG = log.getLogger(__name__)


class RouterTestObj(object):

    def __init__(self, neutron, nb_api):
        self.router_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.closed = False

    def create(self, router={'name': 'myrouter1', 'admin_state_up': True}):
        new_router = self.neutron.create_router({'router': router})
        self.router_id = new_router['router']['id']
        return self.router_id

    def close(self):
        if self.closed or self.router_id is None:
            return
        ports = self.neutron.list_ports(device_id=self.router_id)
        ports = ports['ports']
        for port in ports:
            if port['device_owner'] == 'network:router_interface':
                for fip in port['fixed_ips']:
                    subnet_msg = {'subnet_id': fip['subnet_id']}
                    self.neutron.remove_interface_router(
                         self.router_id, body=subnet_msg)
            elif port['device_owner'] == 'network:router_gateway':
                pass
            else:
                self.neutron.delete_port(port['id'])
        self.neutron.delete_router(self.router_id)
        self.closed = True

    def exists(self):
        routers = self.nb_api.get_routers()
        for router in routers:
            if router.get_name() == self.router_id:
                return True
        return False

    def add_interface(self, port_id=None, subnet_id=None):
        body = {}
        if port_id:
            body['port_id'] = port_id
        if subnet_id:
            body['subnet_id'] = subnet_id
        return self.neutron.add_interface_router(self.router_id, body=body)


class SecGroupTestObj(object):

    def __init__(self, neutron, nb_api):
        self.secgroup_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.closed = False

    def create(self, secgroup={'name': 'mysecgroup1'}):
        new_secgroup = self.neutron.create_security_group({'security_group':
                                                           secgroup})
        self.secgroup_id = new_secgroup['security_group']['id']
        return self.secgroup_id

    def close(self):
        if self.closed or self.secgroup_id is None:
            return
        self.neutron.delete_security_group(self.secgroup_id)
        self.closed = True

    def exists(self):
        secgroups = self.nb_api.get_security_groups()
        for secgroup in secgroups:
            if secgroup.name == self.secgroup_id:
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
        secgroups = self.nb_api.get_security_groups()
        for secgroup in secgroups:
            if secgroup.name == self.secgroup_id:
                for rule in secgroup.rules:
                    if rule.id == secrule_id:
                        return True
        return False


class NetworkTestObj(object):

    def __init__(self, neutron, nb_api):
        self.network_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.closed = False

    def create(self, network={'name': 'mynetwork1', 'admin_state_up': True}):
        network = self.neutron.create_network({'network': network})
        self.network_id = network['network']['id']
        return self.network_id

    def close(self):
        if self.closed or self.network_id is None:
            return
        self.neutron.delete_network(self.network_id)
        self.closed = True

    def exists(self):
        network = self.nb_api.get_lswitch(self.network_id)
        if network:
            return True
        return False


class VMTestObj(object):

    def __init__(self, parent, neutron):
        self.server = None
        self.closed = False
        self.parent = parent
        self.neutron = neutron
        creds = test_base.credentials()
        auth_url = creds['auth_url'] + "/v2.0"
        self.nova = novaclient.Client('2', creds['username'],
                        creds['password'], 'demo', auth_url)

    def create(self, script=None):
        image = self.nova.images.find(name="cirros-0.3.4-x86_64-uec")
        self.parent.assertIsNotNone(image)
        flavor = self.nova.flavors.find(name="m1.tiny")
        self.parent.assertIsNotNone(flavor)
        network = self._find_first_network(name='private')
        self.parent.assertIsNotNone(network)
        nics = [{'net-id': network['id']}]
        self.server = self.nova.servers.create(name='test', image=image.id,
                           flavor=flavor.id, nics=nics, user_data=script)
        self.parent.assertIsNotNone(self.server)
        server_is_ready = self._wait_for_server_ready(30)
        self.parent.assertTrue(server_is_ready)
        return self.server.id

    def _find_first_network(self, **kwargs):
        networks = self.neutron.list_networks(**kwargs)['networks']
        networks_count = len(networks)
        if networks_count == 0:
            return None
        if networks_count > 1:
            message = _LW("More than one network (%(count)d) found matching: "
                "%(args)s")
            LOG.warning(message % {'args': kwargs, 'count': networks_count})
        return networks[0]

    def _wait_for_server_ready(self, timeout):
        if self.server is None:
            return False
        while timeout > 0:
            server = self.nova.servers.find(id=self.server.id)
            if server is not None and server.status == 'ACTIVE':
                return True
            time.sleep(1)
            timeout = timeout - 1
        return False

    def close(self):
        if self.closed or self.server is None:
            return
        self.nova.servers.delete(self.server)
        self.closed = True

    def exists(self):
        if self.server is None:
            return False
        server = self.nova.servers.find(id=self.server.id)
        if server is None:
            return False
        return True

    def dump(self):
        return self.nova.servers.get_console_output(self.server)

    def get_first_ipv4(self):
        if self.server is None:
            return None
        ips = self.server.networks['private']
        for ip in ips:
            if netaddr.IPAddress(ip).version == 4:
                return ip
        return None


class SubnetTestObj(object):
    def __init__(self, neutron, nb_api, network_id=None):
        self.neutron = neutron
        self.nb_api = nb_api
        self.network_id = network_id
        self.subnet_id = None
        self.closed = False

    def create(self, subnet=None):
        if not subnet:
            subnet = {
                'cidr': '192.168.199.0/24',
                'ip_version': 4,
                'network_id': self.network_id
            }
        subnet = self.neutron.create_subnet(body={'subnet': subnet})
        self.subnet_id = subnet['subnet']['id']
        return self.subnet_id

    def get_subnet(self):
        network = self.nb_api.get_lswitch(self.network_id)
        if not network:
            return None
        subnets = network.get_subnets()
        for subnet in subnets:
            if subnet.get_id() == self.subnet_id:
                return subnet
        return None

    def exists(self):
        subnet = self.get_subnet()
        if subnet:
            return True
        return False

    def close(self):
        if self.closed or self.subnet_id is None:
            return
        self.neutron.delete_subnet(self.subnet_id)
        self.closed = True


class PortTestObj(object):

    def __init__(self, neutron, nb_api, network_id=None):
        self.neutron = neutron
        self.nb_api = nb_api
        self.network_id = network_id
        self.port_id = None
        self.closed = False

    def create(self, port=None):
        if not port:
            port = {
                'admin_state_up': True,
                'name': 'port1',
                'network_id': self.network_id,
            }
        port = self.neutron.create_port(body={'port': port})
        self.port_id = port['port']['id']
        return self.port_id

    def get_logical_port(self):
        return self.nb_api.get_logical_port(self.port_id)

    def exists(self):
        port = self.get_logical_port()
        if port:
            return True
        return False

    def close(self):
        if self.closed or self.port_id is None:
            return
        self.neutron.delete_port(self.port_id)
        self.closed = True


class FloatingipTestObj(object):

    def __init__(self, neutron, nb_api):
        self.floatingip_id = None
        self.neutron = neutron
        self.nb_api = nb_api
        self.closed = False

    def create(self, floatingip):
        floatingip = self.neutron.create_floatingip(
            {'floatingip': floatingip})
        self.floatingip_id = floatingip['floatingip']['id']
        return floatingip['floatingip']

    def update(self, floatingip):
        floatingip = self.neutron.update_floatingip(
            self.floatingip_id,
            {'floatingip': floatingip})
        return floatingip['floatingip']

    def close(self):
        if self.closed or self.floatingip_id is None:
            return
        self.neutron.delete_floatingip(self.floatingip_id)
        self.closed = True

    def get_floatingip(self):
        return self.nb_api.get_floatingip(self.floatingip_id)

    def exists(self):
        floatingip = self.nb_api.get_floatingip(self.floatingip_id)
        if floatingip:
            return True
        return False
