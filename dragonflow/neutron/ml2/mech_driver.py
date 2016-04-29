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

from dragonflow._i18n import _LI
from dragonflow.common import common_params
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.common import constants as df_const

from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.common import constants as n_const
from neutron.db import db_base_plugin_v2
from neutron.db import securitygroups_db
from neutron.extensions import portbindings
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api

from oslo_config import cfg
from oslo_log import log
from oslo_utils import importutils

LOG = log.getLogger(__name__)
cfg.CONF.register_opts(common_params.df_opts, 'df')


class DFMechDriver(driver_api.MechanismDriver,
                   db_base_plugin_v2.NeutronDbPluginV2,
                   securitygroups_db.SecurityGroupDbMixin):

    """Dragonflow ML2 MechanismDriver for Neutron.

    """
    def initialize(self):
        LOG.info(_LI("Starting DFMechDriver"))

        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        self.vif_type = portbindings.VIF_TYPE_OVS
        self._set_base_port_binding()

        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=True)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

        registry.subscribe(self.post_fork_initialize, resources.PROCESS,
                           events.AFTER_CREATE)
        registry.subscribe(self.create_security_group,
                           resources.SECURITY_GROUP,
                           events.AFTER_CREATE)
        registry.subscribe(self.delete_security_group,
                           resources.SECURITY_GROUP,
                           events.BEFORE_DELETE)
        registry.subscribe(self.create_security_group_rule,
                           resources.SECURITY_GROUP_RULE,
                           events.AFTER_CREATE)
        registry.subscribe(self.delete_security_group_rule,
                           resources.SECURITY_GROUP_RULE,
                           events.BEFORE_DELETE)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP)
    def create_security_group(self, resource, event, trigger, **kwargs):
        sg = kwargs['security_group']
        sg_name = sg['id']
        tenant_id = sg['tenant_id']
        rules = sg.get('security_group_rules')
        self.nb_api.create_security_group(name=sg_name, topic=tenant_id,
                                          rules=rules)
        LOG.info(_LI("DFMechDriver: create security group %s") % sg_name)
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
        self.nb_api.add_security_group_rules(sg_id, [sg_rule],
                                             sg_rule['tenant_id'])
        LOG.info(_LI("DFMechDriver: create security group rule in group %s"),
                 sg_id)
        return sg_rule

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP_RULE_DELETE)
    def delete_security_group_rule(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        tenant_id = context.tenant_id
        sgr_id = kwargs['security_group_rule_id']
        sgr = self.get_security_group_rule(context, sgr_id)
        sg_id = sgr['security_group_id']
        self.nb_api.delete_security_group_rule(sg_id, sgr_id, tenant_id)
        LOG.info(_LI("DFMechDriver: delete security group rule %s"), sgr_id)

    def post_fork_initialize(self, resource, event, trigger, **kwargs):
        self._set_base_port_binding()

    def _set_base_port_binding(self):
        self.base_binding_dict = {
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
            portbindings.VIF_DETAILS: {
                # TODO(rkukura): Replace with new VIF security details
                portbindings.CAP_PORT_FILTER:
                'security-group' in self.supported_extension_aliases}}

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_network_postcommit(self, context):
        network = context.current
        external_ids = {df_const.DF_NETWORK_NAME_EXT_ID_KEY: network['name']}
        self.nb_api.create_lswitch(name=network['id'],
                                   topic=network['tenant_id'],
                                   external_ids=external_ids,
                                   subnets=[])
        LOG.info(_LI("DFMechDriver: create network %s"), network['id'])
        return network

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_network_postcommit(self, context):
        network = context.current
        network_id = network['id']
        tenant_id = network['tenant_id']

        for port in self.nb_api.get_all_logical_ports(topic=tenant_id):
            if port.get_lswitch_id() == network_id:
                try:
                    self.nb_api.delete_lport(name=port.get_id(),
                                             topic=tenant_id)
                    LOG.info(_LI("DFMechDriver: delete port %(port)s when "
                                 "delete network %(network)s"),
                             {'port': port.get_id(), 'network': network_id})
                except df_exceptions.DBKeyNotFound:
                    LOG.debug("port %s is not found in DB, might have "
                              "been deleted concurrently" % port.get_id())

        try:
            self.nb_api.delete_lswitch(name=network_id, topic=tenant_id)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("lswitch %s is not found in DF DB, might have "
                      "been deleted concurrently" % network_id)

        LOG.info(_LI("DFMechDriver: delete network %s"), network_id)

    def _get_dhcp_port_for_subnet(self, context, subnet_id):
        filters = {'fixed_ips': {'subnet_id': [subnet_id]},
                   'device_owner': [n_const.DEVICE_OWNER_DHCP]}
        ports = context._plugin.get_ports(context, filters=filters)
        if 0 != len(ports):
            return ports[0]
        else:
            return None

    def _get_ip_from_port(self, port):
        """Get The first Ip address from the port.

        Returns the first fixed_ip address for a port
        """
        if not port:
            return None
        for fixed_ip in port['fixed_ips']:
            if "ip_address" in fixed_ip:
                return fixed_ip['ip_address']

    def _get_subnet_dhcp_port_address(self, context, subnet):
        """Create the dhcp configration for the subnet

        Returns the dhcp server ip address if configured
        """
        try:
            dhcp_port = self._get_dhcp_port_for_subnet(context, subnet['id'])
            dhcp_address = self._get_ip_from_port(dhcp_port)
            return dhcp_address
        except Exception as e:
            LOG.exception(e)
            return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_subnet_postcommit(self, context):
        subnet = context.current
        net_id = subnet['network_id']

        if subnet['enable_dhcp']:
            dhcp_address = self._get_subnet_dhcp_port_address(context, subnet)
        else:
            dhcp_address = None

        # update df controller with subnet
        self.nb_api.add_subnet(
            subnet['id'],
            net_id,
            subnet['tenant_id'],
            enable_dhcp=subnet['enable_dhcp'],
            cidr=subnet['cidr'],
            dhcp_ip=dhcp_address,
            gateway_ip=subnet['gateway_ip'],
            dns_nameservers=subnet.get('dns_nameservers', []))

        LOG.info(_LI("DFMechDriver: create subnet %s"), subnet['id'])
        return subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def update_subnet_postcommit(self, context):
        new_subnet = context.current

        if new_subnet['enable_dhcp']:
            dhcp_address = self._get_subnet_dhcp_port_address(context,
                                                              new_subnet)
        else:
            dhcp_address = None

        # update df controller with subnet
        self.nb_api.update_subnet(
            new_subnet['id'],
            new_subnet['network_id'],
            new_subnet['tenant_id'],
            enable_dhcp=new_subnet['enable_dhcp'],
            cidr=new_subnet['cidr'],
            dhcp_ip=dhcp_address,
            gateway_ip=new_subnet['gateway_ip'],
            dns_nameservers=new_subnet.get('dns_nameservers', []))

        LOG.info(_LI("DFMechDriver: update subnet %s"), new_subnet['id'])
        return new_subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_subnet_postcommit(self, context):
        subnet = context.current
        net_id = subnet['network_id']

        # update df controller with subnet delete
        try:
            self.nb_api.delete_subnet(subnet['id'], net_id,
                                      subnet['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("network %s is not found in DB, might have "
                      "been deleted concurrently" % net_id)

        LOG.info(_LI("DFMechDriver: delete subnet %s"), subnet['id'])

    def _get_allowed_mac_addresses_from_port(self, port):
        allowed_macs = set()
        allowed_macs.add(port['mac_address'])
        allowed_address_pairs = port.get('allowed_address_pairs', [])
        for allowed_address in allowed_address_pairs:
            allowed_macs.add(allowed_address['mac_address'])
        return list(allowed_macs)

    def create_port_in_nb_api(self, port, sgids):
        # The port name *must* be port['id'].  It must match the iface-id set
        # in the Interfaces table of the Open_vSwitch database, which nova sets
        # to be the port ID.
        external_ids = {df_const.DF_PORT_NAME_EXT_ID_KEY: port['name']}
        allowed_macs = self._get_allowed_mac_addresses_from_port(port)
        ips = []

        if 'fixed_ips' in port:
            ips = [ip['ip_address'] for ip in port['fixed_ips']]

        chassis = None
        if 'binding:host_id' in port:
            chassis = port['binding:host_id']

        tunnel_key = self.nb_api.allocate_tunnel_key()

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if port.get('device_owner') == n_const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        self.nb_api.create_lport(
            name=port['id'],
            lswitch_name=port['network_id'],
            topic=port['tenant_id'],
            macs=[port['mac_address']], ips=ips,
            external_ids=external_ids,
            enabled=port.get('admin_state_up', None),
            chassis=chassis, tunnel_key=tunnel_key,
            port_security=allowed_macs,
            device_owner=port.get('device_owner', None),
            sgids=sgids)

        return port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def create_port_postcommit(self, context):
        port = context.current
        plugin_context = context._plugin_context
        port['port'] = port
        sgids = super(DFMechDriver, self)._get_security_groups_on_port(
            plugin_context, port)
        self.create_port_in_nb_api(port, sgids)
        LOG.info(_LI("DFMechDriver: create port %s"), port['id'])
        return port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def update_port_postcommit(self, context):
        updated_port = context.current
        external_ids = {
            df_const.DF_PORT_NAME_EXT_ID_KEY: updated_port['name']}
        allowed_macs = self._get_allowed_mac_addresses_from_port(
            updated_port)

        ips = []
        if 'fixed_ips' in updated_port:
            ips = [ip['ip_address'] for ip in updated_port['fixed_ips']]

        chassis = None
        if 'binding:host_id' in updated_port:
            chassis = updated_port['binding:host_id']

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if updated_port.get('device_owner') == n_const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        updated_security_groups = updated_port.get('security_groups')
        if updated_security_groups == []:
            security_groups = None
        else:
            security_groups = updated_security_groups

        self.nb_api.update_lport(name=updated_port['id'],
                                 topic=updated_port['tenant_id'],
                                 macs=[updated_port['mac_address']], ips=ips,
                                 external_ids=external_ids,
                                 enabled=updated_port['admin_state_up'],
                                 port_security=allowed_macs,
                                 chassis=chassis,
                                 device_owner=updated_port.get('device_owner',
                                                               None),
                                 security_groups=security_groups)

        LOG.info(_LI("DFMechDriver: update port %s"), updated_port['id'])
        return updated_port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_CORE)
    def delete_port_postcommit(self, context):
        try:
            port = context.current
            port_id = port['id']
            topic = port['tenant_id']
            self.nb_api.delete_lport(name=port_id, topic=topic)
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
            if self.check_segment(segment):
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

    def check_segment(self, segment):
        """Verify a segment is valid for the dragonflow MechanismDriver."""
        return segment[driver_api.NETWORK_TYPE] in [constants.TYPE_VLAN,
                                                    constants.TYPE_VXLAN,
                                                    constants.TYPE_FLAT,
                                                    constants.TYPE_GRE,
                                                    constants.TYPE_LOCAL]
