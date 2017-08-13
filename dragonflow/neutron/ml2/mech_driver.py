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

from neutron.plugins.ml2 import models
from neutron_lib.api.definitions import portbindings
from neutron_lib.api import validators
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as n_const
from neutron_lib import exceptions as n_exc
from neutron_lib.plugins import directory
from neutron_lib.plugins.ml2 import api
from oslo_log import log

from dragonflow._i18n import _
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.db.models import l2
from dragonflow.db.models import secgroups
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.common import constants as df_const
from dragonflow.neutron.db.models import l2 as neutron_l2
from dragonflow.neutron.db.models import secgroups as neutron_secgroups
from dragonflow.neutron.services.qos.drivers import df_qos
from dragonflow.neutron.services.trunk import driver as trunk_driver

LOG = log.getLogger(__name__)


class DFMechDriver(api.MechanismDriver):

    """Dragonflow ML2 MechanismDriver for Neutron.

    """

    supported_extension_aliases = ['security-group',
                                   'extra_dhcp_opt',
                                   'binding',
                                   'external-net',
                                   'port-security',
                                   'allowed-address-pairs',
                                   'net-mtu',
                                   'trunk']

    def initialize(self):
        LOG.info("Starting DFMechDriver")
        self.nb_api = None

        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        self.vif_type = portbindings.VIF_TYPE_OVS
        self._set_base_port_binding()
        self.port_status = n_const.PORT_STATUS_ACTIVE
        self.trunk_driver = trunk_driver.DragonflowDriver()
        self.subscribe_registries()
        df_qos.register()

    def post_fork_initialize(self, resource, event, trigger, **kwargs):
        # NOTE(nick-ma-z): This will initialize all workers (API, RPC,
        # plugin service, etc) and threads with network connections.
        self.nb_api = api_nb.NbApi.get_instance(True)
        df_qos.initialize(self.nb_api)
        if cfg.CONF.df.enable_neutron_notifier:
            neutron_notifier = df_utils.load_driver(
                cfg.CONF.df.neutron_notifier,
                df_utils.DF_NEUTRON_NOTIFIER_DRIVER_NAMESPACE)
            neutron_notifier.initialize(self.nb_api,
                                        is_neutron_server=True)
            self.port_status = None

    def subscribe_registries(self):
        registry.subscribe(self.post_fork_initialize,
                           resources.PROCESS,
                           events.AFTER_INIT)

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

    @property
    def core_plugin(self):
        return directory.get_plugin()

    def _get_attribute(self, obj, attribute):
        res = obj.get(attribute)
        if res is n_const.ATTR_NOT_SPECIFIED:
            res = None
        return res

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
        sg_name = sg.get('name', df_const.DF_SG_DEFAULT_NAME)
        rules = sg.get('security_group_rules', [])

        for rule in rules:
            rule['topic'] = rule.get('tenant_id')
            del rule['tenant_id']
        sg_obj = neutron_secgroups.security_group_from_neutron_obj(sg)
        if event == events.AFTER_CREATE:
            self.nb_api.create(sg_obj)
            LOG.info("DFMechDriver: create security group %s", sg_name)
        elif event == events.AFTER_UPDATE:
            self.nb_api.update(sg_obj)
            LOG.info("DFMechDriver: update security group %s", sg_name)

        return sg_obj

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP)
    def delete_security_group(self, resource, event, trigger, **kwargs):
        sg = kwargs['security_group']
        sg_obj = secgroups.SecurityGroup(id=sg['id'], topic=sg['tenant_id'])
        self.nb_api.delete(sg_obj)
        LOG.info("DFMechDriver: delete security group %s", sg['id'])

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP_RULE_CREATE)
    def create_security_group_rule(self, resource, event, trigger, **kwargs):
        sg_rule = kwargs['security_group_rule']
        sg_id = sg_rule['security_group_id']
        context = kwargs['context']

        sg = self.core_plugin.get_security_group(context, sg_id)
        sg_obj = neutron_secgroups.security_group_from_neutron_obj(sg)
        self.nb_api.update(sg_obj)
        LOG.info("DFMechDriver: create security group rule in group %s", sg_id)
        return sg_rule

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP_RULE_DELETE)
    def delete_security_group_rule(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        sgr_id = kwargs['security_group_rule_id']
        sg_id = kwargs['security_group_id']

        sg = self.core_plugin.get_security_group(context, sg_id)
        sg_obj = neutron_secgroups.security_group_from_neutron_obj(sg)
        self.nb_api.update(sg_obj)
        LOG.info("DFMechDriver: delete security group rule %s", sgr_id)

    def create_network_precommit(self, context):
        # TODO(xiaohhui): Multi-provider networks are not supported yet.
        network = context.current
        if self._get_attribute(network, 'segments'):
            msg = _('Multi-provider networks are not supported')
            raise n_exc.InvalidInput(error_message=msg)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def create_network_postcommit(self, context):
        network = context.current

        lswitch = neutron_l2.logical_switch_from_neutron_network(network)
        self.nb_api.create(lswitch)

        LOG.info("DFMechDriver: create network %s", network['id'])
        return network

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def delete_network_postcommit(self, context):
        network = context.current
        network_id = network['id']
        tenant_id = network['tenant_id']

        try:
            self.nb_api.delete(l2.LogicalSwitch(id=network_id,
                                                topic=tenant_id))
        except df_exceptions.DBKeyNotFound:
            LOG.debug("lswitch %s is not found in DF DB, might have "
                      "been deleted concurrently", network_id)
            return

        LOG.info("DFMechDriver: delete network %s", network_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def update_network_postcommit(self, context):
        network = context.current

        lswitch = neutron_l2.logical_switch_from_neutron_network(network)
        self.nb_api.update(lswitch)

        LOG.info("DFMechDriver: update network %s", network['id'])
        return network

    def _get_dhcp_port_for_subnet(self, context, subnet_id):
        filters = {'fixed_ips': {'subnet_id': [subnet_id]},
                   'device_owner': [n_const.DEVICE_OWNER_DHCP]}
        ports = self.core_plugin.get_ports(context, filters=filters)
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
        port = {'port': {'tenant_id': subnet['tenant_id'],
                         'network_id': subnet['network_id'], 'name': '',
                         'admin_state_up': True, 'device_id': '',
                         'device_owner': n_const.DEVICE_OWNER_DHCP,
                         'mac_address': n_const.ATTR_NOT_SPECIFIED,
                         'fixed_ips': [{'subnet_id': subnet['id']}]}}
        port = self.core_plugin.create_port(context, port)
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
            ip = fixed_ip.get('ip_address')
            if ip:
                return ip

        return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SUBNET)
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
        except Exception:
            LOG.exception(
                "Failed to create dhcp port for subnet %s", subnet['id'])
            return None

        lswitch = self.nb_api.get(l2.LogicalSwitch(id=net_id,
                                                   topic=network['tenant_id']))
        lswitch.version = network['revision_number']
        df_subnet = neutron_l2.subnet_from_neutron_subnet(subnet)
        df_subnet.dhcp_ip = dhcp_ip
        lswitch.add_subnet(df_subnet)
        self.nb_api.update(lswitch)

        LOG.info("DFMechDriver: create subnet %s", subnet['id'])
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
        self.core_plugin.delete_port(context, port['id'])

    def _handle_update_subnet_dhcp(self, context, old_subnet, new_subnet):
        """Update the dhcp configuration for.

        Returns the dhcp ip if exists and optionaly value of dhcp server port
        if this port was created.
        """
        dhcp_ip = None
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            dhcp_ip = self._update_subnet_dhcp_centralized(context, new_subnet)
            return dhcp_ip, None

        if new_subnet['enable_dhcp']:
            if not old_subnet['enable_dhcp']:
                port = self._create_dhcp_server_port(context, new_subnet)
            else:
                port = self._get_dhcp_port_for_subnet(context,
                                                      old_subnet['id'])

            return self._get_ip_from_port(port), port
        else:
            if old_subnet['enable_dhcp']:
                port = self._get_dhcp_port_for_subnet(context,
                                                      old_subnet['id'])
                self._delete_subnet_dhcp_port(context, port)

            return None, None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SUBNET)
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
        except Exception:
            LOG.exception(
                "Failed to create dhcp port for subnet %s", new_subnet['id'])
            return None

        lswitch = self.nb_api.get(l2.LogicalSwitch(id=new_subnet['network_id'],
                                                   topic=network['tenant_id']))
        lswitch.version = network['revision_number']
        subnet = lswitch.find_subnet(new_subnet['id'])
        subnet.update(neutron_l2.subnet_from_neutron_subnet(new_subnet))
        subnet.dhcp_ip = dhcp_ip
        self.nb_api.update(lswitch)

        LOG.info("DFMechDriver: update subnet %s", new_subnet['id'])
        return new_subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SUBNET)
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
        network = self.core_plugin.get_network(context._plugin_context,
                                               net_id)

        try:
            lswitch = self.nb_api.get(l2.LogicalSwitch(
                id=net_id, topic=network['tenant_id']))
            lswitch.remove_subnet(subnet_id)
            lswitch.version = network['revision_number']
            self.nb_api.update(lswitch)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("network %s is not found in DB, might have "
                      "been deleted concurrently", net_id)
            return

        LOG.info("DFMechDriver: delete subnet %s", subnet_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def create_port_postcommit(self, context):
        port = context.current

        lport = neutron_l2.logical_port_from_neutron_port(port)
        self.nb_api.create(lport)

        LOG.info("DFMechDriver: create port %s", port['id'])
        return port

    def _is_dhcp_port_after_subnet_delete(self, port):
        # If a subnet enabled dhcp, the DFMechDriver will create a dhcp server
        # port. When delete this subnet, the port should be deleted.
        # In ml2/plugin.py, when delete subnet, it will call
        # update_port_postcommit, DFMechDriver should judge the port is dhcp
        # port or not, if it is, then delete it.
        subnet_id = None

        for fixed_ip in port['fixed_ips']:
            subnet_id = fixed_ip.get('subnet_id')
            if subnet_id:
                break

        owner = port['device_owner']
        return owner == n_const.DEVICE_OWNER_DHCP and subnet_id is None

    def update_port_precommit(self, context):
        port = context.current
        neutron_l2.validate_extra_dhcp_option(port)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def update_port_postcommit(self, context):
        updated_port = context.current
        lean_port = l2.LogicalPort(id=updated_port['id'],
                                   topic=updated_port['tenant_id'])
        if not self.nb_api.get(lean_port):
            # REVISIT(xiaohhui): Should we unify the check before update nb db?
            LOG.debug("The port %s has been deleted from dragonflow NB DB, "
                      "by concurrent operation.", updated_port['id'])
            return

        # Here we do not want port status update to trigger
        # sending event to other compute node.
        if (cfg.CONF.df.enable_neutron_notifier and
                n_const.DEVICE_OWNER_COMPUTE_PREFIX
                in updated_port['device_owner'] and
                context.status != context.original_status and
                (context.status == n_const.PORT_STATUS_DOWN or
                 context.status == n_const.PORT_STATUS_ACTIVE)):
            return None

        # If a subnet enabled dhcp, the DFMechDriver will create a dhcp server
        # port. When delete this subnet, the port should be deleted.
        # In ml2/plugin.py, when delete subnet, it will call
        # update_port_postcommit, DFMechDriver should judge the port is dhcp
        # port or not, if it is, then delete it.
        if self._is_dhcp_port_after_subnet_delete(updated_port):
            self._delete_subnet_dhcp_port(context._plugin_context,
                                          updated_port)
            return None

        lport = neutron_l2.logical_port_from_neutron_port(updated_port)
        self.nb_api.update(lport)

        LOG.info("DFMechDriver: update port %s", updated_port['id'])
        return updated_port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def delete_port_postcommit(self, context):
        port = context.current
        port_id = port['id']
        lean_port = l2.LogicalPort(id=port_id,
                                   topic=port['tenant_id'])
        try:
            self.nb_api.delete(lean_port)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("port %s is not found in DF DB, might have "
                      "been deleted concurrently", port_id)
            return

        LOG.info("DFMechDriver: delete port %s", port_id)

    def bind_port(self, context):
        """Set porting binding data for use with nova."""
        LOG.debug("Attempting to bind port %(port)s on "
                  "network %(network)s",
                  {'port': context.current['id'],
                   'network': context.network.current['id']})

        # Prepared porting binding data
        for segment in context.segments_to_bind:
            if self._check_segment(segment):
                context.set_binding(segment[api.ID],
                                    self.vif_type,
                                    self.vif_details,
                                    status=self.port_status)
                LOG.debug("Bound using segment: %s", segment)
                return
            else:
                LOG.debug("Refusing to bind port for segment ID %(id)s, "
                          "segment %(seg)s, phys net %(physnet)s, and "
                          "network type %(nettype)s",
                          {'id': segment[api.ID],
                           'seg': segment[api.SEGMENTATION_ID],
                           'physnet': segment[api.PHYSICAL_NETWORK],
                           'nettype': segment[api.NETWORK_TYPE]})

    def _check_segment(self, segment):
        """Verify a segment is valid for the dragonflow MechanismDriver."""
        return segment[api.NETWORK_TYPE] in [n_const.TYPE_VLAN,
                                             n_const.TYPE_VXLAN,
                                             n_const.TYPE_FLAT,
                                             n_const.TYPE_GENEVE,
                                             n_const.TYPE_GRE,
                                             n_const.TYPE_LOCAL]
