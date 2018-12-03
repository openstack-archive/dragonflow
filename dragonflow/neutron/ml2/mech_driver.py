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
from dragonflow.neutron.db.models import l2 as neutron_l2
from dragonflow.neutron.db.models import secgroups as neutron_secgroups
from dragonflow.neutron.ml2 import dhcp_module
from dragonflow.neutron.services.lbaas import vip_port_enabler
from dragonflow.neutron.services.qos.drivers import df_qos
from dragonflow.neutron.services.trunk import driver as trunk_driver
from dragonflow.neutron.services.trunk import port_behind_port

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
        self.trunk_driver = trunk_driver.DfTrunkDriver()
        if cfg.CONF.df.auto_detect_port_behind_port:
            self._port_behind_port_detector = (
                port_behind_port.DfPortBehindPortDetector())
        if cfg.CONF.df_loadbalancer.auto_enable_vip_ports:
            self._vip_port_enabler = vip_port_enabler.DfLBaaSVIPPortEnabler()
        self.subscribe_registries()
        df_qos.register()
        self.dhcp_module = dhcp_module.DFDHCPModule()

    def post_fork_initialize(self, resource, event, trigger, **kwargs):
        # NOTE(nick-ma-z): This will initialize all workers (API, RPC,
        # plugin service, etc) and threads with network connections.
        self.nb_api = api_nb.NbApi.get_instance()
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
        sg_name = sg.get('name')
        rules = sg.get('security_group_rules', [])

        for rule in rules:
            try:
                rule['topic'] = rule.pop('project_id')
            except KeyError:
                rule['topic'] = rule.pop('tenant_id', None)
        sg_obj = neutron_secgroups.security_group_from_neutron_obj(sg)
        if event == events.AFTER_CREATE:
            self.nb_api.create(sg_obj)
            LOG.info("DFMechDriver: create security group %s", sg_name)
        elif event == events.AFTER_UPDATE:
            self.nb_api.update(sg_obj)
            LOG.info("DFMechDriver: update security group %s", sg_name)

        return sg_obj

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SECURITY_GROUP)
    def delete_security_group(self, resource, event, trigger, payload=None):
        sg = payload.latest_state
        topic = df_utils.get_obj_topic(sg)
        sg_obj = secgroups.SecurityGroup(id=sg['id'], topic=topic)
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

        topic = df_utils.get_obj_topic(network)
        try:
            self.nb_api.delete(l2.LogicalSwitch(id=network_id,
                                                topic=topic))
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
        df_subnet = neutron_l2.subnet_from_neutron_subnet(subnet)
        self.nb_api.create(df_subnet)
        topic = df_utils.get_obj_topic(network)
        self.nb_api.update(l2.LogicalSwitch(
            id=net_id, topic=topic,
            version=network['revision_number']))

        LOG.info("DFMechDriver: create subnet %s", subnet['id'])
        return subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SUBNET)
    def update_subnet_postcommit(self, context):
        new_subnet = context.current
        subnet = neutron_l2.subnet_from_neutron_subnet(new_subnet)
        self.nb_api.update(subnet)
        network = context.network.current
        topic = df_utils.get_obj_topic(network)
        self.nb_api.update(l2.LogicalSwitch(
            id=network['id'], topic=topic,
            version=network['revision_number']))

        LOG.info("DFMechDriver: update subnet %s", new_subnet['id'])
        return new_subnet

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_SUBNET)
    def delete_subnet_postcommit(self, context):

        subnet = context.current
        net_id = subnet['network_id']
        subnet_id = subnet['id']
        # The network in context is still the network before deleting subnet
        network = self.core_plugin.get_network(context._plugin_context,
                                               net_id)

        try:
            topic = df_utils.get_obj_topic(network)
            self.nb_api.delete(l2.Subnet(id=subnet_id))
            self.nb_api.update(l2.LogicalSwitch(
                id=net_id, topic=topic,
                version=network['revision_number']))
        except df_exceptions.DBKeyNotFound:
            LOG.debug("network %s is not found in DB, might have "
                      "been deleted concurrently", net_id)
            return

        LOG.info("DFMechDriver: delete subnet %s", subnet_id)

    def _get_lswitch_topic(self, port):
        lswitch = self.nb_api.get(l2.LogicalSwitch(id=port['network_id']))
        return lswitch.topic

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def create_port_postcommit(self, context):
        port = context.current

        lport = neutron_l2.logical_port_from_neutron_port(port)

        # Update topic for FIP ports
        if lport.topic == '':
            lport.topic = self._get_lswitch_topic(port)

        self.nb_api.create(lport)

        LOG.info("DFMechDriver: create port %s", port['id'])
        return port

    def update_port_precommit(self, context):
        port = context.current
        neutron_l2.validate_extra_dhcp_option(port)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def update_port_postcommit(self, context):
        updated_port = context.current
        topic = df_utils.get_obj_topic(updated_port)
        lean_port = l2.LogicalPort(id=updated_port['id'],
                                   topic=topic)
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

        lport = neutron_l2.logical_port_from_neutron_port(updated_port)
        # Update topic for FIP ports
        if lport.topic == '':
            lport.topic = self._get_lswitch_topic(updated_port)
        self.nb_api.update(lport)

        LOG.info("DFMechDriver: update port %s", updated_port['id'])
        return updated_port

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ML2_NETWORK_OR_PORT)
    def delete_port_postcommit(self, context):
        port = context.current
        port_id = port['id']
        topic = df_utils.get_obj_topic(port)
        lean_port = l2.LogicalPort(id=port_id,
                                   topic=topic)

        # Update topic for FIP ports
        if lean_port.topic == '':
            lean_port.topic = self._get_lswitch_topic(port)
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
