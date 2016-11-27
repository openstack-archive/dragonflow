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
from oslo_serialization import jsonutils


UNIQUE_KEY = 'unique_key'


class NbObject(object):

    def __init__(self, inner_obj):
        super(NbObject, self).__init__()
        self.inner_obj = inner_obj

    def get_id(self):
        """Return the ID of this object."""
        return self.inner_obj.get('id')

    def get_topic(self):
        """
        Return the topic, i.e. ID of the tenant to which this object belongs.
        """
        return self.inner_obj.get('topic')

    def __str__(self):
        return str(self.inner_obj)

    # NOTE(xiaohhui): In python3, add customized __eq__ will make object
    # unhashable. If the models in this module need to be hashable, customized
    # __hash__ will be required.
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.inner_obj == other.inner_obj
        else:
            return False


class NbDbObject(NbObject):

    def __init__(self, value):
        inner_obj = jsonutils.loads(value)
        super(NbDbObject, self).__init__(inner_obj)

    def get_name(self):
        return self.inner_obj.get('name')

    def get_version(self):
        return self.inner_obj.get('version')


class NbDbObjectWithUniqueKey(NbDbObject):

    def get_unique_key(self):
        return self.inner_obj.get(UNIQUE_KEY)


class Chassis(NbDbObject):

    def get_ip(self):
        return self.inner_obj.get('ip')

    def get_encap_type(self):
        return self.inner_obj.get('tunnel_type')

    def get_topic(self):
        return None

    def get_name(self):
        return self.get_id()

    def get_version(self):
        return None


class LogicalSwitch(NbDbObjectWithUniqueKey):

    def is_external(self):
        return self.inner_obj.get('router_external')

    def get_mtu(self):
        return self.inner_obj.get('mtu')

    def get_subnets(self):
        subnets = self.inner_obj.get('subnets')
        if subnets:
            return [Subnet(subnet) for subnet in subnets]
        else:
            return []

    def get_segment_id(self):
        return self.inner_obj.get('segmentation_id')

    def get_network_type(self):
        return self.inner_obj.get('network_type')

    def get_physical_network(self):
        return self.inner_obj.get('physical_network')


class Subnet(NbObject):

    def enable_dhcp(self):
        return self.inner_obj.get('enable_dhcp')

    def get_name(self):
        return self.inner_obj.get('name')

    def get_dhcp_server_address(self):
        return self.inner_obj.get('dhcp_ip')

    def get_cidr(self):
        return self.inner_obj.get('cidr')

    def get_gateway_ip(self):
        return self.inner_obj.get('gateway_ip')

    def get_dns_name_servers(self):
        return self.inner_obj.get('dns_nameservers', [])

    def get_host_routes(self):
        return self.inner_obj.get('host_routes', [])


class LogicalPort(NbDbObjectWithUniqueKey):

    def __init__(self, value):
        super(LogicalPort, self).__init__(value)
        self.external_dict = {}

    def get_ip(self):
        ip_list = self.get_ip_list()
        if ip_list:
            return ip_list[0]

    def get_ip_list(self):
        return self.inner_obj.get('ips', [])

    def get_subnets(self):
        return self.inner_obj.get('subnets', [])

    def get_mac(self):
        if self.inner_obj.get('macs'):
            return self.inner_obj['macs'][0]

    def get_chassis(self):
        return self.inner_obj.get('chassis')

    def get_lswitch_id(self):
        return self.inner_obj.get('lswitch')

    def get_tunnel_key(self):
        # TODO(xiaohhui): This should be replaced with get_unique_key
        return int(self.inner_obj['tunnel_key'])

    def get_security_groups(self):
        return self.inner_obj.get('security_groups', [])

    def get_allow_address_pairs(self):
        return self.inner_obj.get('allowed_address_pairs', [])

    def get_port_security_enable(self):
        return self.inner_obj.get('port_security_enabled', False)

    def set_external_value(self, key, value):
        self.external_dict[key] = value

    def get_external_value(self, key):
        return self.external_dict.get(key)

    def get_device_owner(self):
        return self.inner_obj.get('device_owner')

    def get_device_id(self):
        return self.inner_obj.get('device_id')

    def get_binding_profile(self):
        return self.inner_obj.get('binding_profile')

    def get_binding_vnic_type(self):
        return self.inner_obj.get('binding_vnic_type')

    def get_qos_policy_id(self):
        return self.inner_obj.get('qos_policy_id')

    def get_remote_vtep(self):
        return self.inner_obj.get('remote_vtep', False)

    def __str__(self):
        lport_with_exteral_dict = dict(self.inner_obj)
        lport_with_exteral_dict['external_dict'] = self.external_dict
        return str(lport_with_exteral_dict)


class LogicalRouter(NbDbObject):

    def get_ports(self):
        ports = self.inner_obj.get('ports')
        if ports:
            return [LogicalRouterPort(port) for port in ports]
        else:
            return []

    def get_routes(self):
        return self.inner_obj.get('routes', [])

    def is_distributed(self):
        return self.inner_obj.get('distributed', False)

    def get_external_gateway(self):
        return self.inner_obj.get('gateway', {})


class LogicalRouterPort(NbObject):

    def __init__(self, lroute_port):
        super(LogicalRouterPort, self).__init__(lroute_port)
        self.cidr = netaddr.IPNetwork(self.inner_obj['network'])

    def get_ip(self):
        return str(self.cidr.ip)

    def get_cidr_network(self):
        return str(self.cidr.network)

    def get_cidr_netmask(self):
        return str(self.cidr.netmask)

    def get_mac(self):
        return self.inner_obj.get('mac')

    def get_lswitch_id(self):
        return self.inner_obj.get('lswitch')

    def get_network(self):
        return self.inner_obj.get('network')

    def get_tunnel_key(self):
        return self.inner_obj.get('tunnel_key')


class SecurityGroup(NbDbObjectWithUniqueKey):

    def get_rules(self):
        rules = self.inner_obj.get('rules')
        if rules:
            return [SecurityGroupRule(rule) for rule in rules]
        else:
            return []


class SecurityGroupRule(NbObject):

    def get_direction(self):
        return self.inner_obj.get('direction')

    def get_ethertype(self):
        return self.inner_obj.get('ethertype')

    def get_port_range_max(self):
        return self.inner_obj.get('port_range_max')

    def get_port_range_min(self):
        return self.inner_obj.get('port_range_min')

    def get_protocol(self):
        return self.inner_obj.get('protocol')

    def get_remote_group_id(self):
        return self.inner_obj.get('remote_group_id')

    def get_remote_ip_prefix(self):
        return self.inner_obj.get('remote_ip_prefix')

    def get_security_group_id(self):
        return self.inner_obj.get('security_group_id')


class Floatingip(NbDbObject):

    def get_status(self):
        return self.inner_obj.get('status')

    def update_fip_status(self, status):
        self.inner_obj['status'] = status

    def get_ip_address(self):
        return self.inner_obj.get('floating_ip_address')

    def get_mac_address(self):
        return self.inner_obj.get('floating_mac_address')

    def get_lport_id(self):
        return self.inner_obj.get('port_id')

    def get_fixed_ip_address(self):
        return self.inner_obj.get('fixed_ip_address')

    def get_lrouter_id(self):
        return self.inner_obj.get('router_id')

    def get_external_gateway_ip(self):
        return self.inner_obj.get('external_gateway_ip')

    def set_external_gateway_ip(self, gw_ip):
        self.inner_obj['external_gateway_ip'] = gw_ip

    def get_floating_network_id(self):
        return self.inner_obj.get('floating_network_id')

    def get_external_cidr(self):
        return self.inner_obj.get('external_cidr')

    def get_floating_port_id(self):
        return self.inner_obj.get('floating_port_id')


class QosPolicy(NbDbObject):

    def get_type(self):
        return self.inner_obj.get('type')

    def get_max_burst_kbps(self):
        rules = self.inner_obj.get('rules', [])
        max_burst_kbps = None
        for rule in rules:
            if rule['type'] == 'bandwidth_limit':
                max_burst_kbps = rule.get('max_burst_kbps')
                break

        return max_burst_kbps

    def get_max_kbps(self):
        rules = self.inner_obj.get('rules', [])
        max_kbps = None
        for rule in rules:
            if rule['type'] == 'bandwidth_limit':
                max_kbps = rule.get('max_kbps')
                break

        return max_kbps

    def get_dscp_marking(self):
        rules = self.inner_obj.get('rules', [])
        dscp_marking = None
        for rule in rules:
            if rule['type'] == 'dscp_marking':
                dscp_marking = rule.get('dscp_mark')
                break

        return dscp_marking


class Publisher(NbDbObject):

    def get_uri(self):
        return self.inner_obj.get('uri')

    def get_last_activity_timestamp(self):
        return self.inner_obj.get('last_activity_timestamp')


class OvsPort(object):

    TYPE_VM = 'vm'
    TYPE_TUNNEL = 'tunnel'
    TYPE_BRIDGE = 'bridge'
    TYPE_PATCH = 'patch'

    def __init__(self, value):
        self.ovs_port = value

    def get_id(self):
        return self.ovs_port.get_id()

    def get_ofport(self):
        return self.ovs_port.get_ofport()

    def get_name(self):
        return self.ovs_port.get_name()

    def get_admin_state(self):
        return self.ovs_port.get_admin_state()

    def get_type(self):
        return self.ovs_port.get_type()

    def get_iface_id(self):
        return self.ovs_port.get_iface_id()

    def get_peer(self):
        return self.ovs_port.get_peer()

    def get_attached_mac(self):
        return self.ovs_port.get_attached_mac()

    def get_mac_in_use(self):
        return self.ovs_port.get_mac_in_use()

    def get_remote_ip(self):
        return self.ovs_port.get_remote_ip()

    def get_remote_chassis(self):
        return self.ovs_port.get_remote_chassis()

    def get_tunnel_type(self):
        return self.ovs_port.get_tunnel_type()

    def __str__(self):
        return str(self.ovs_port)


class Listener(NbDbObject):
    def get_id(self):
        return self.inner_obj['id']

    def get_topic(self):
        return 'n_listener' + '_' + self.inner_obj['id']

    def get_timestamp(self):
        return self.inner_obj['timestamp']

    def get_ppid(self):
        return self.inner_obj['ppid']

    def get_name(self):
        return self.inner_obj.get('name')

    def get_version(self):
        return self.inner_obj.get('version')

    def __str__(self):
        return str(self.inner_obj)

