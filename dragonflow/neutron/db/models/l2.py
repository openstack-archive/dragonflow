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

from neutron.extensions import allowedaddresspairs as addr_pair
from neutron_lib.api.definitions import extra_dhcp_opt
from neutron_lib.api.definitions import port_security as psec
from neutron_lib.api.definitions import portbindings
from neutron_lib.api import validators

from dragonflow.db.models import l2
from dragonflow.neutron.common import constants as df_const


def logical_switch_from_neutron_network(network):
    return l2.LogicalSwitch(
        id=network['id'],
        topic=network['tenant_id'],
        name=network.get('name', df_const.DF_NETWORK_DEFAULT_NAME),
        network_type=network.get('provider:network_type'),
        physical_network=network.get('provider:physical_network'),
        segmentation_id=network.get('provider:segmentation_id'),
        is_external=network['router:external'],
        mtu=network.get('mtu'),
        version=network['revision_number'],
        qos_policy=network.get('qos_policy_id'))


def subnet_from_neutron_subnet(subnet):
    return l2.Subnet(
        id=subnet['id'],
        topic=subnet['tenant_id'],
        name=subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
        enable_dhcp=subnet['enable_dhcp'],
        cidr=subnet['cidr'],
        gateway_ip=subnet['gateway_ip'],
        dns_nameservers=subnet.get('dns_nameservers', []),
        host_routes=subnet.get('host_routes', []))


def _validate_ip_prefix_allowed_address_pairs(allowed_address_pairs):
    """
    Dragonflow only supports host IPs in allowed address pairs. This method
    validates that no network IPs (prefix IPs) are given in the allowed
    address pairs.
    """
    if not validators.is_attr_set(allowed_address_pairs):
        return []

    # Not support IP address prefix yet
    for pair in allowed_address_pairs:
        if '/' in pair["ip_address"]:
            raise Exception(_("DF don't support IP prefix in allowed"
                              "address pairs yet. The allowed address"
                              "pair {ip_address = %(ip_address), "
                              "mac_address = %(mac_address)} "
                              "caused this exception.} "),
                            {'ip_address': pair["ip_address"],
                             'mac_address': pair["mac_address"]})

    supported_allowed_address_pairs = list(allowed_address_pairs)
    return supported_allowed_address_pairs


def _build_extra_dhcp_options(port):
    dhcp_opt_dict = {}
    opts = port.get(extra_dhcp_opt.EXTRADHCPOPTS, [])

    for opt in opts:
        dhcp_opt_dict[opt['opt_name']] = opt['opt_value']

    return dhcp_opt_dict


def logical_port_from_neutron_port(port):
    return l2.LogicalPort(
            id=port['id'],
            lswitch=port['network_id'],
            topic=port['tenant_id'],
            macs=[port['mac_address']],
            ips=[ip['ip_address'] for ip in port.get('fixed_ips', [])],
            subnets=[ip['subnet_id'] for ip in port.get('fixed_ips', [])],
            name=port.get('name', df_const.DF_PORT_DEFAULT_NAME),
            enabled=port.get('admin_state_up', False),
            version=port['revision_number'],
            device_owner=port.get('device_owner'),
            device_id=port.get('device_id'),
            security_groups=port.get('security_groups', []),
            port_security_enabled=port.get(psec.PORTSECURITY, False),
            allowed_address_pairs=_validate_ip_prefix_allowed_address_pairs(
                port.get(addr_pair.ADDRESS_PAIRS, [])),
            binding_vnic_type=port.get(portbindings.VNIC_TYPE),
            qos_policy=port.get('qos_policy_id'),
            extra_dhcp_options=_build_extra_dhcp_options(port))
