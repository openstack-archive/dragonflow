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

from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.extensions import allowedaddresspairs as addr_pair
from neutron.extensions import portbindings
from neutron.extensions import portsecurity as psec
from neutron import manager
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api
from neutron.plugins.ml2 import models
from neutron_lib.api import validators
from neutron_lib import constants as n_const
from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI, _LE
from dragonflow.common import common_params
from dragonflow.common import constants as df_common_const
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.common import constants as df_const

LOG = log.getLogger(__name__)
cfg.CONF.register_opts(common_params.df_opts, 'df')


class DFMechDriver(driver_api.MechanismDriver):

    """Dragonflow ML2 MechanismDriver for Neutron.

    """

    supported_extension_aliases = ['security-group',
                                   'extra_dhcp_opt'
                                   'binding',
                                   'external-net',
                                   'port-security',
                                   'allowed-address-pairs',
                                   'net-mtu']

    def initialize(self):
        LOG.info(_LI("Starting DFMechDriver"))

        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        self.vif_type = portbindings.VIF_TYPE_OVS
        self._set_base_port_binding()

        self.nb_api = api_nb.NbApi.get_instance(True)

        registry.subscribe(self.update_security_group,
                           resources.SECURITY_GROUP,
                           events.AFTER_CREATE)
        registry.subscribe(self.update_security_group,
                           resources.SECURITY_GROUP,
                           events.AFTER_UPDATE)
        registry.subscribe(self.delete_security_group,
                           resources.SECURITY_GROUP,
                           events.BEFORE_DELETE)
        registry.subscribe(self.create_security_group_rule,
                           resources.SECURITY_GROUP_RULE,
                           events.AFTER_CREATE)
        registry.subscribe(self.delete_security_group_rule,
                           resources.SECURITY_GROUP_RULE,
                           events.AFTER_DELETE)

    def _set_base_port_binding(self):
        if cfg.CONF.df.vif_type == portbindings.VIF_TYPE_VHOST_USER:
            self.base_binding_dict = {
                portbindings.VIF_TYPE: portbindings.VIF_TYPE_VHOST_USER,
                portbindings.VIF_DETAILS: {
                    # TODO(nick-ma-z): VIF security is disabled for vhu port.
                    # This will be revisited if the function is supported by
                    # OVS upstream.
                    portbindings.CAP_PORT_FILTER: False,
                    portbindings.VHOST_USER_MODE:
                    portbindings.VHOST_USER_MODE_CLIENT,
                    portbindings.VHOST_USER_OVS_PLUG: True,
                }
            }
        else:
            self.base_binding_dict = {
                portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
                portbindings.VIF_DETAILS: {
                    # TODO(rkukura): Replace with new VIF security details
                    portbindings.CAP_PORT_FILTER:
                    'security-group' in self.supported_extension_aliases}}

    def _update_port_binding(self, port_res):
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL
        if cfg.CONF.df.vif_type == portbindings.VIF_TYPE_VHOST_USER:
            port_res[portbindings.VIF_DETAILS].update({
                portbindings.VHOST_USER_SOCKET: df_utils.get_vhu_sockpath(
                    cfg.CONF.df.vhost_sock_dir, port_res['id']
                )
            })

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP)
    def update_security_group(self, resource, event, trigger, **kwargs):
        sg = kwargs['security_group']
        sg_id = sg['id']
        sg_name = sg.get('name', df_const.DF_SG_DEFAULT_NAME)
        tenant_id = sg['tenant_id']
        rules = sg.get('security_group_rules', [])
        sg_version = sg['revision_number']

        for rule in rules:
            rule['topic'] = rule.get('tenant_id')
            del rule['tenant_id']
        if event == events.AFTER_CREATE:
            self.nb_api.create_security_group(id=sg_id, topic=tenant_id,
                                              name=sg_name, rules=rules,
                                              version=sg_version)
            LOG.info(_LI("DFMechDriver: create security group %s"), sg_name)
        elif event == events.AFTER_UPDATE:
            self.nb_api.update_security_group(id=sg_id, topic=tenant_id,
                                              name=sg_name, rules=rules,
                                              version=sg_version)
            LOG.info(_LI("DFMechDriver: update security group %s"), sg_name)

        return sg

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP)
    def delete_security_group(self, resource, event, trigger, **kwargs):
        sg = kwargs['security_group']
        sg_id = kwargs['security_group_id']
        tenant_id = sg['tenant_id']

        self.nb_api.delete_security_group(sg_id, topic=tenant_id)
        LOG.info(_LI("DFMechDriver: delete security group %s") % sg_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP_RULE_CREATE)
    def create_security_group_rule(self, resource, event, trigger, **kwargs):
        sg_rule = kwargs['security_group_rule']
        sg_id = sg_rule['security_group_id']
        tenant_id = sg_rule['tenant_id']
        context = kwargs['context']

        core_plugin = manager.NeutronManager.get_plugin()
        sg = core_plugin.get_security_group(context, sg_id)
        sg_version = sg['revision_number']

        sg_rule['topic'] = tenant_id
        del sg_rule['tenant_id']
        self.nb_api.add_security_group_rules(sg_id, tenant_id,
                                             sg_rules=[sg_rule],
                                             sg_version=sg_version)
        LOG.info(_LI("DFMechDriver: create security group rule in group %s"),
                 sg_id)
        return sg_rule

    def _get_security_group_id_from_security_group_rule(self, sgr_id):
        # TODO(xiaohhui): For now, query security_group from nb DB. Once
        # https://review.openstack.org/#/c/367728/ has been merged, just
        # get security_group from neutron DB and remove this method.
        security_groups = self.nb_api.get_security_groups()
        for sg in security_groups:
            for sg_rule in sg.get_rules():
                if sgr_id == sg_rule.get_id():
                    return sg.get_id()

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP_RULE_DELETE)
    def delete_security_group_rule(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        sgr_id = kwargs['security_group_rule_id']

        sg_id = self._get_security_group_id_from_security_group_rule(sgr_id)
        if not sg_id:
            # There is no such security group in nb DB. No other operations
            # required.
            LOG.error(_LE("Can't find security group for deleted security "
                          "group rule %s"), sgr_id)
            return

        core_plugin = manager.NeutronManager.get_plugin()
        sg = core_plugin.get_security_group(context, sg_id)
        sg_version = sg['revision_number']
        tenant_id = sg['tenant_id']

        self.nb_api.delete_security_group_rule(sg_id, sgr_id, tenant_id,
                                               sg_version=sg_version)
        LOG.info(_LI("DFMechDriver: delete security group rule %s"), sgr_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_network_postcommit(self, context):
        network = context.current

        self.nb_api.create_lswitch(
            id=network['id'],
            topic=network['tenant_id'],
            name=network.get('name', df_const.DF_NETWORK_DEFAULT_NAME),
            network_type=network.get('provider:network_type'),
            segmentation_id=network.get('provider:segmentation_id'),
            router_external=network['router:external'],
            mtu=network.get('mtu'),
            version=network['revision_number'],
            subnets=[])

        LOG.info(_LI("DFMechDriver: create network %s"), network['id'])
        return network

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_network_postcommit(self, context):
        network = context.current
        network_id = network['id']
        tenant_id = network['tenant_id']

        try:
            self.nb_api.delete_lswitch(id=network_id,
                                       topic=tenant_id)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("lswitch %s is not found in DF DB, might have "
                      "been deleted concurrently" % network_id)

        LOG.info(_LI("DFMechDriver: delete network %s"), network_id)

    def _get_dhcp_port_for_subnet(self, context, subnet_id):
        filters = {'fixed_ips': {'subnet_id': [subnet_id]},
                   'device_owner': [n_const.DEVICE_OWNER_DHCP]}

        core_plugin = manager.NeutronManager.get_plugin()
        ports = core_plugin.get_ports(context, filters=filters)
        if 0 != len(ports):
            return ports[0]
        else:
            return None

    def _process_portbindings_create_and_update(self, context, port_data,
                                                port):
        binding_profile = port.get(portbindings.PROFILE)
        binding_profile_set = validators.is_attr_set(binding_profile)
        if not binding_profile_set and binding_profile is not None:
            del port[portbindings.PROFILE]

        binding_vnic = port.get(portbindings.VNIC_TYPE)
        binding_vnic_set = validators.is_attr_set(binding_vnic)
        if not binding_vnic_set and binding_vnic is not None:
            del port[portbindings.VNIC_TYPE]

        host = port_data.get(portbindings.HOST_ID)
        host_set = validators.is_attr_set(host)
        with context.session.begin(subtransactions=True):
            bind_port = context.session.query(
                models.PortBinding).filter_by(port_id=port['id']).first()
            if host_set:
                if not bind_port:
                    context.session.add(models.PortBinding(
                        port_id=port['id'],
                        host=host,
                        vif_type=self.vif_type))
                else:
                    bind_port.host = host
            else:
                host = bind_port.host if bind_port else None
        self._extend_port_dict_binding_host(port, host)

    def extend_port_dict_binding(self, port_res, port_db):
        self._update_port_binding(port_res)
        super(DFMechDriver, self).extend_port_dict_binding(port_res, port_db)

    def _create_dhcp_server_port(self, context, subnet):
        """Create and return dhcp port information.

        If an expected failure occurs, a None port is returned.
        """
        port = {'port': {'tenant_id': context.tenant_id,
                         'network_id': subnet['network_id'], 'name': '',
                         'binding:host_id': (
                             df_common_const.DRAGONFLOW_VIRTUAL_PORT),
                         'admin_state_up': True, 'device_id': '',
                         'device_owner': n_const.DEVICE_OWNER_DHCP,
                         'mac_address': n_const.ATTR_NOT_SPECIFIED,
                         'fixed_ips': [{'subnet_id': subnet['id']}]}}

        core_plugin = manager.NeutronManager.get_plugin()
        port = core_plugin.create_port(context, port)

        return port

    def _handle_create_subnet_dhcp(self, context, subnet):
        """Create the dhcp configuration for the subnet if required.

        Returns the dhcp ip and dhcp server port (if created).
        """
        if subnet['enable_dhcp']:
            if cfg.CONF.df.use_centralized_ipv6_DHCP:
                return subnet['allocation_pools'][0]['start'], None
            else:

                dhcp_port = self._create_dhcp_server_port(context, subnet)
                dhcp_ip = self._get_ip_from_port(dhcp_port)
                return dhcp_ip, dhcp_port
        return None, None

    def _get_ip_from_port(self, port):
        """Get The first Ip address from the port.

        Returns the first fixed_ip address for a port
        """
        if not port:
            return None

        for fixed_ip in port['fixed_ips']:
            ip = fixed_ip.get('ip_address', None)
            if ip:
                return ip

        return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_subnet_postcommit(self, context):
        subnet = context.current
        network = context.network.current
        net_id = subnet['network_id']
        plugin_context = context._plugin_context
        dhcp_ip = None
        dhcp_port = None

        try:
            dhcp_ip, dhcp_port = self._handle_create_subnet_dhcp(
                                                plugin_context,
                                                subnet)
        except Exception as e:
            LOG.exception(e)
            return None

        self.nb_api.add_subnet(
            subnet['id'],
            net_id,
            subnet['tenant_id'],
            name=subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
            nw_version=network['revision_number'],
            enable_dhcp=subnet['enable_dhcp'],
            cidr=subnet['cidr'],
            dhcp_ip=dhcp_ip,
            gateway_ip=subnet['gateway_ip'],
            dns_nameservers=subnet.get('dns_nameservers', []),
            host_routes=subnet.get('host_routes', []))

        LOG.info(_LI("DFMechDriver: create subnet %s"), subnet['id'])
        return subnet

    def _update_subnet_dhcp_centralized(self, context, subnet):
        """Update the dhcp configuration for the subnet.

        Returns the dhcp server ip address if configured
        """
        if subnet['enable_dhcp']:
            port = self._get_dhcp_port_for_subnet(
                    context,
                    subnet['id'])
            return self._get_ip_from_port(port)
        else:
            return subnet['allocation_pools'][0]['start']

    def _delete_subnet_dhcp_port(self, context, port):
        core_plugin = manager.NeutronManager.get_plugin()
        core_plugin.delete_port(context, port['id'])

    def _handle_update_subnet_dhcp(self, context, old_subnet, new_subnet):
        """Update the dhcp configuration for.

        Returns the dhcp ip if exists and optionaly value of dhcp server port
        if this port was created.
        """
        dhcp_ip = None
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            dhcp_ip = self._update_subnet_dhcp_centralized(context, new_subnet)
            return dhcp_ip, None

        if old_subnet['enable_dhcp']:
            port = self._get_dhcp_port_for_subnet(context, old_subnet['id'])

        if not new_subnet['enable_dhcp'] and old_subnet['enable_dhcp']:
            if port:
                self._delete_subnet_dhcp_port(context, port)
            return None, None
        if new_subnet['enable_dhcp'] and not old_subnet['enable_dhcp']:
            port = self._create_dhcp_server_port(context, new_subnet)
            dhcp_ip = self._get_ip_from_port(port)
            return dhcp_ip, port
        if port:
            dhcp_ip = self._get_ip_from_port(port)
        return dhcp_ip, None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def update_subnet_postcommit(self, context):
        new_subnet = context.current
        old_subnet = context.original
        network = context.network.current
        plugin_context = context._plugin_context
        dhcp_ip = None
        dhcp_port = None

        try:
            dhcp_ip, dhcp_port = self._handle_update_subnet_dhcp(
                                                    plugin_context,
                                                    old_subnet,
                                                    new_subnet)
        except Exception as e:
            LOG.exception(e)
            return None

        self.nb_api.update_subnet(
            new_subnet['id'],
            new_subnet['network_id'],
            new_subnet['tenant_id'],
            name=new_subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
            nw_version=network['revision_number'],
            enable_dhcp=new_subnet['enable_dhcp'],
            cidr=new_subnet['cidr'],
            dhcp_ip=dhcp_ip,
            gateway_ip=new_subnet['gateway_ip'],
            dns_nameservers=new_subnet.get('dns_nameservers', []),
            host_routes=new_subnet.get('host_routes', []))

        LOG.info(_LI("DFMechDriver: update subnet %s"), new_subnet['id'])
        return new_subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_subnet_postcommit(self, context):
        """If the subnet enabled dhcp, the dhcp server port should be deleted.
        But the operation of delete dhcp port can't do here, because in this
        case, we can't get dhcp port by subnet id. The dhcp port will be
        deleted in update_port_postcommit.
        """
        subnet = context.current
        net_id = subnet['network_id']
        subnet_id = subnet['id']

        # The network in context is still the network before deleting subnet
        core_plugin = manager.NeutronManager.get_plugin()
        network = core_plugin.get_network(context._plugin_context, net_id)

        # update df controller with subnet delete
        try:
            self.nb_api.delete_subnet(subnet_id, net_id, subnet['tenant_id'],
                                      nw_version=network['revision_number'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("network %s is not found in DB, might have "
                      "been deleted concurrently" % net_id)

        LOG.info(_LI("DFMechDriver: delete subnet %s"), subnet_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_port_postcommit(self, context):
        port = context.current
        ips = [ip['ip_address'] for ip in port.get('fixed_ips', [])]
        subnets = [ip['subnet_id'] for ip in port.get('fixed_ips', [])]
        tunnel_key = self.nb_api.allocate_tunnel_key()

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if port.get('device_owner') == n_const.DEVICE_OWNER_ROUTER_GW:
            chassis = None
        else:
            chassis = port.get('binding:host_id', None) or None

        binding_profile = port.get('binding:profile')
        remote_vtep = False
        if binding_profile and binding_profile.get(
                df_const.DF_BINDING_PROFILE_PORT_KEY) ==\
                df_const.DF_REMOTE_PORT_TYPE:
            chassis = binding_profile.get(df_const.DF_BINDING_PROFILE_HOST_IP)
            remote_vtep = True

        self.nb_api.create_lport(
            id=port['id'],
            lswitch_id=port['network_id'],
            topic=port['tenant_id'],
            macs=[port['mac_address']], ips=ips,
            subnets=subnets,
            name=port.get('name', df_const.DF_PORT_DEFAULT_NAME),
            enabled=port.get('admin_state_up', False),
            chassis=chassis, tunnel_key=tunnel_key,
            version=port['revision_number'],
            device_owner=port.get('device_owner', None),
            device_id=port.get('device_id', None),
            security_groups=port.get('security_groups', []),
            port_security_enabled=port.get(psec.PORTSECURITY, False),
            remote_vtep=remote_vtep,
            allowed_address_pairs=port.get(addr_pair.ADDRESS_PAIRS, []),
            binding_profile=port.get(portbindings.PROFILE, None),
            binding_vnic_type=port.get(portbindings.VNIC_TYPE, None))

        LOG.info(_LI("DFMechDriver: create port %s"), port['id'])
        return port

    def _is_dhcp_port_after_subnet_delete(self, port):
        # If a subnet enabled dhcp, the DFMechDriver will create a dhcp server
        # port. When delete this subnet, the port should be deleted.
        # In ml2/plugin.py, when delete subnet, it will call
        # update_port_postcommit, DFMechDriver should judge the port is dhcp
        # port or not, if it is, then delete it.
        host_id = port.get('binding:host_id', None)
        subnet_id = None

        for fixed_ip in port['fixed_ips']:
            subnet_id = fixed_ip.get('subnet_id', None)
            if subnet_id:
                break

        if host_id == df_common_const.DRAGONFLOW_VIRTUAL_PORT \
                and subnet_id is None:
            return True
        else:
            return False

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def update_port_postcommit(self, context):
        updated_port = context.current
        if not self.nb_api.get_logical_port(updated_port['id'],
                                            updated_port['tenant_id']):
            # REVISIT(xiaohhui): Should we unify the check before update nb db?
            LOG.debug("The port %s has been deleted from dragonflow NB DB, "
                      "by concurrent operation.", updated_port['id'])
            return

        # If a subnet enabled dhcp, the DFMechDriver will create a dhcp server
        # port. When delete this subnet, the port should be deleted.
        # In ml2/plugin.py, when delete subnet, it will call
        # update_port_postcommit, DFMechDriver should judge the port is dhcp
        # port or not, if it is, then delete it.
        if self._is_dhcp_port_after_subnet_delete(updated_port):
            self._delete_subnet_dhcp_port(context._plugin_context,
                                          updated_port)
            return None

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if updated_port.get('device_owner') == n_const.DEVICE_OWNER_ROUTER_GW:
            chassis = None
        else:
            chassis = updated_port.get('binding:host_id', None) or None

        binding_profile = updated_port.get('binding:profile')
        remote_vtep = False
        if binding_profile and binding_profile.get(
                df_const.DF_BINDING_PROFILE_PORT_KEY) ==\
                df_const.DF_REMOTE_PORT_TYPE:
            chassis = binding_profile.get(df_const.DF_BINDING_PROFILE_HOST_IP)
            remote_vtep = True

        updated_security_groups = updated_port.get('security_groups')
        if updated_security_groups:
            security_groups = updated_security_groups
        else:
            security_groups = []

        ips = [ip['ip_address'] for ip in updated_port.get('fixed_ips', [])]
        subnets = [ip['subnet_id'] for ip in updated_port.get('fixed_ips', [])]

        self.nb_api.update_lport(
            id=updated_port['id'],
            topic=updated_port['tenant_id'],
            macs=[updated_port['mac_address']],
            ips=ips,
            subnets=subnets,
            name=updated_port.get('name', df_const.DF_PORT_DEFAULT_NAME),
            enabled=updated_port['admin_state_up'],
            chassis=chassis,
            device_owner=updated_port.get('device_owner', None),
            device_id=updated_port.get('device_id', None),
            security_groups=security_groups,
            port_security_enabled=updated_port.get(psec.PORTSECURITY, False),
            allowed_address_pairs=updated_port.get(addr_pair.ADDRESS_PAIRS,
                                                   []),
            binding_profile=updated_port.get(portbindings.PROFILE, None),
            binding_vnic_type=updated_port.get(portbindings.VNIC_TYPE, None),
            version=updated_port['revision_number'], remote_vtep=remote_vtep)

        LOG.info(_LI("DFMechDriver: update port %s"), updated_port['id'])
        return updated_port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_port_postcommit(self, context):
        port = context.current
        port_id = port['id']

        try:
            topic = port['tenant_id']
            self.nb_api.delete_lport(id=port_id, topic=topic)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("port %s is not found in DF DB, might have "
                      "been deleted concurrently" % port_id)

        LOG.info(_LI("DFMechDriver: delete port %s"), port_id)

    def bind_port(self, context):
        """Set porting binding data for use with nova."""
        LOG.debug("Attempting to bind port %(port)s on "
                  "network %(network)s",
                  {'port': context.current['id'],
                   'network': context.network.current['id']})

        # Prepared porting binding data
        for segment in context.segments_to_bind:
            if self._check_segment(segment):
                context.set_binding(segment[driver_api.ID],
                                    self.vif_type,
                                    self.vif_details,
                                    status=n_const.PORT_STATUS_ACTIVE)
                LOG.debug("Bound using segment: %s", segment)
                return
            else:
                LOG.debug("Refusing to bind port for segment ID %(id)s, "
                          "segment %(seg)s, phys net %(physnet)s, and "
                          "network type %(nettype)s",
                          {'id': segment[driver_api.ID],
                           'seg': segment[driver_api.SEGMENTATION_ID],
                           'physnet': segment[driver_api.PHYSICAL_NETWORK],
                           'nettype': segment[driver_api.NETWORK_TYPE]})

    def _check_segment(self, segment):
        """Verify a segment is valid for the dragonflow MechanismDriver."""
        return segment[driver_api.NETWORK_TYPE] in [constants.TYPE_VLAN,
                                                    constants.TYPE_VXLAN,
                                                    constants.TYPE_FLAT,
                                                    constants.TYPE_GENEVE,
                                                    constants.TYPE_GRE,
                                                    constants.TYPE_LOCAL]
