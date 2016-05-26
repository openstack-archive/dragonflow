#
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
import six

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import importutils
from sqlalchemy.orm import exc as sa_exc

from neutron.api.rpc.agentnotifiers import dhcp_rpc_agent_api
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import dhcp_rpc
from neutron.api.rpc.handlers import l3_rpc
from neutron.api.rpc.handlers import metadata_rpc
from neutron.api.v2 import attributes as attr
from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.common import exceptions as n_exc
from neutron.extensions import allowedaddresspairs as addr_pair
from neutron.extensions import extra_dhcp_opt as edo_ext
from neutron.extensions import portbindings
from neutron.extensions import portsecurity as psec
from neutron.extensions import providernet as pnet

from neutron.common import constants as const
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.common import utils
from neutron.db import agents_db
from neutron.db import agentschedulers_db
from neutron.db import allowedaddresspairs_db as addr_pair_db
from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_attrs_db
from neutron.db import l3_db
from neutron.db import l3_gwmode_db
from neutron.db import models_v2
from neutron.db import portbindings_db
from neutron.db import portsecurity_db_common
from neutron.db import securitygroups_db
from neutron.quota import resource_registry

from dragonflow._i18n import _, _LE, _LI
from dragonflow.common import common_params
from dragonflow.common import constants as df_common_const
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import extensions
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db.neutron import versionobjects_db as version_db
from dragonflow.neutron.common import constants as df_const

LOG = log.getLogger(__name__)

cfg.CONF.register_opts(common_params.df_opts, 'df')

router_distributed_opts = [
    cfg.BoolOpt('router_distributed',
                default=False,
                help=_("System-wide flag to determine the type of router "
                       "that tenants can create. Only admin can override.")),
]
cfg.CONF.register_opts(router_distributed_opts)


class DFPlugin(db_base_plugin_v2.NeutronDbPluginV2,
               securitygroups_db.SecurityGroupDbMixin,
               l3_agentschedulers_db.L3AgentSchedulerDbMixin,
               l3_gwmode_db.L3_NAT_db_mixin,
               l3_attrs_db.ExtraAttributesMixin,
               external_net_db.External_net_db_mixin,
               portbindings_db.PortBindingMixin,
               portsecurity_db_common.PortSecurityDbCommon,
               addr_pair_db.AllowedAddressPairsMixin,
               extradhcpopt_db.ExtraDhcpOptMixin,
               extraroute_db.ExtraRoute_db_mixin,
               agentschedulers_db.DhcpAgentSchedulerDbMixin):

    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    supported_extension_aliases = extensions.SUPPORTED_API_EXTENSIONS

    extra_attributes = (
        l3_attrs_db.ExtraAttributesMixin.extra_attributes + [{
            'name': "distributed",
            'default': cfg.CONF.router_distributed
        }])

    @resource_registry.tracked_resources(
        network=models_v2.Network,
        port=models_v2.Port,
        subnet=models_v2.Subnet,
        subnetpool=models_v2.SubnetPool,
        security_group=securitygroups_db.SecurityGroup,
        security_group_rule=securitygroups_db.SecurityGroupRule,
        router=l3_db.Router,
        floatingip=l3_db.FloatingIP)
    def __init__(self):
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver)
        super(DFPlugin, self).__init__()
        LOG.info(_LI("Starting DFPlugin"))
        self.vif_type = portbindings.VIF_TYPE_OVS
        self._set_base_port_binding()
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        registry.subscribe(self.post_fork_initialize, resources.PROCESS,
                           events.AFTER_CREATE)

        self._setup_dhcp()
        self._start_rpc_notifiers()

    def post_fork_initialize(self, resource, event, trigger, **kwargs):
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)

        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=True)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

        self._set_base_port_binding()

    def _set_base_port_binding(self):
        self.base_binding_dict = {
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
            portbindings.VIF_DETAILS: {
                # TODO(rkukura): Replace with new VIF security details
                portbindings.CAP_PORT_FILTER:
                'security-group' in self.supported_extension_aliases}}

    def _setup_dhcp(self):
        """Initialize components to support DHCP."""
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            self.network_scheduler = importutils.import_object(
                cfg.CONF.network_scheduler_driver
            )
            self.start_periodic_dhcp_agent_status_check()

    def _setup_rpc(self):

        self.endpoints = [l3_rpc.L3RpcCallback(),
                          agents_db.AgentExtRpcCallback(),
                          metadata_rpc.MetadataRpcCallback()]
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            self.endpoints.append(dhcp_rpc.DhcpRpcCallback())

    def _start_rpc_notifiers(self):
        """Initialize RPC notifiers for agents."""

        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            self.agent_notifiers[const.AGENT_TYPE_DHCP] = (
                dhcp_rpc_agent_api.DhcpAgentNotifyAPI()
            )

        self.agent_notifiers[const.AGENT_TYPE_L3] = (
            l3_rpc_agent_api.L3AgentNotifyAPI()
        )

    def start_rpc_listeners(self):
        self._setup_rpc()
        self.conn = n_rpc.create_connection()
        self.conn.create_consumer(topics.PLUGIN, self.endpoints, fanout=False)
        self.conn.create_consumer(topics.L3PLUGIN, self.endpoints,
                                  fanout=False)
        # topics.REPORTS was added for the Mitaka release, therefore, to
        # work with stable/liberty, check to see if topics.REPORTS exists
        # if it does, use it.
        if hasattr(topics, 'REPORTS'):
            self.conn.create_consumer(
                topics.REPORTS, [agents_db.AgentExtRpcCallback()],
                fanout=False)
        return self.conn.consume_in_threads()

    def _delete_ports(self, context, ports):
        for port in ports:
            try:
                self.delete_port(context, port.id)
            except (n_exc.PortNotFound, sa_exc.ObjectDeletedError):
                context.session.expunge(port)
                # concurrent port deletion can be performed by
                # release_dhcp_port caused by concurrent subnet_delete
                LOG.info(_LI("Port %s was deleted concurrently"), port.id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE("Exception auto-deleting port %s"),
                                  port.id)

    @lock_db.wrap_db_lock()
    def create_security_group(self, context, security_group,
                              default_sg=False):
        with context.session.begin(subtransactions=True):
            sg_db = super(DFPlugin,
                          self).create_security_group(context, security_group,
                                                      default_sg)
            sg_version = version_db._create_db_version_row(
                    context.session, sg_db['id'])
        sg_id = sg_db['id']
        sg_name = sg_db.get('name', df_const.DF_SG_DEFAULT_NAME)
        tenant_id = sg_db['tenant_id']
        rules = sg_db.get('security_group_rules')

        self.nb_api.create_security_group(id=sg_id, topic=tenant_id,
                                          name=sg_name, rules=rules,
                                          version=sg_version)
        return sg_db

    @lock_db.wrap_db_lock()
    def create_security_group_rule(self, context, security_group_rule):
        with context.session.begin(subtransactions=True):
            sg_rule = super(DFPlugin, self).create_security_group_rule(
                context, security_group_rule)
            sg_id = sg_rule['security_group_id']
            sg_version_id = version_db._update_db_version_row(
                    context.session, sg_id)
            sg_group = self.get_security_group(context, sg_id)
        self.nb_api.add_security_group_rules(sg_id, sg_group['tenant_id'],
                                             sg_rules=[sg_rule],
                                             sg_version=sg_version_id)
        return sg_rule

    @lock_db.wrap_db_lock()
    def delete_security_group_rule(self, context, id):
        with context.session.begin(subtransactions=True):
            security_group_rule = self.get_security_group_rule(context, id)
            sg_id = security_group_rule['security_group_id']
            sg_group = self.get_security_group(context, sg_id)
            super(DFPlugin, self).delete_security_group_rule(context, id)
            sg_version_id = version_db._update_db_version_row(
                    context.session, sg_id)
        self.nb_api.delete_security_group_rule(sg_id, id,
                                               sg_group['tenant_id'],
                                               sg_version=sg_version_id)

    @lock_db.wrap_db_lock()
    def delete_security_group(self, context, sg_id):
        sg = self.get_security_group(context, sg_id)
        tenant_id = sg['tenant_id']
        with context.session.begin(subtransactions=True):
            super(DFPlugin, self).delete_security_group(context, sg_id)
            version_db._delete_db_version_row(
                    context.session, sg_id)
        self.nb_api.delete_security_group(sg_id, topic=tenant_id)

    @lock_db.wrap_db_lock()
    def create_subnet(self, context, subnet):
        net_id = subnet['subnet']['network_id']
        new_subnet = None
        dhcp_port = None
        network_version = None

        try:
            with context.session.begin(subtransactions=True):
                # create subnet in DB
                new_subnet = super(DFPlugin,
                                   self).create_subnet(context, subnet)
                dhcp_port = self._handle_create_subnet_dhcp(
                                context, new_subnet)
                network_version = version_db._update_db_version_row(
                        context.session, net_id)
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = True
                # delete the stale dhcp port
                try:
                    if dhcp_port:
                        self.nb_api.delete_lport(dhcp_port['id'],
                                                 dhcp_port['tenant_id'])
                except df_exceptions.DBKeyNotFound:
                    pass

        if new_subnet:
            dhcp_address = self._get_ip_from_port(dhcp_port)
            self.nb_api.add_subnet(
                new_subnet['id'],
                net_id,
                new_subnet['tenant_id'],
                name=new_subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
                nw_version=network_version,
                enable_dhcp=new_subnet['enable_dhcp'],
                cidr=new_subnet['cidr'],
                dhcp_ip=dhcp_address,
                gateway_ip=new_subnet['gateway_ip'],
                dns_nameservers=new_subnet.get('dns_nameservers', []))
        return new_subnet

    @lock_db.wrap_db_lock()
    def update_subnet(self, context, id, subnet):
        dhcp_port = None
        new_subnet = None
        net_id = None
        network_version = None
        try:
            with context.session.begin(subtransactions=True):
                # update subnet in DB
                original_subnet = super(DFPlugin, self).get_subnet(context, id)
                new_subnet = super(DFPlugin,
                                   self).update_subnet(context, id, subnet)
                net_id = new_subnet['network_id']
                dhcp_port = self._update_subnet_dhcp(
                        context, original_subnet, new_subnet)
                network_version = version_db._update_db_version_row(
                        context.session, net_id)
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = True
                # delete the stale dhcp port
                try:
                    if dhcp_port:
                        self.nb_api.delete_lport(dhcp_port['id'],
                                                 dhcp_port['tenant_id'])
                except df_exceptions.DBKeyNotFound:
                    pass

        if new_subnet and net_id:
            # update df controller with subnet
            dhcp_address = self._get_ip_from_port(dhcp_port)
            self.nb_api.update_subnet(
                new_subnet['id'],
                net_id,
                new_subnet['tenant_id'],
                name=new_subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
                nw_version=network_version,
                enable_dhcp=new_subnet['enable_dhcp'],
                cidr=new_subnet['cidr'],
                dhcp_ip=dhcp_address,
                gateway_ip=new_subnet['gateway_ip'],
                dns_nameservers=new_subnet.get('dns_nameservers', []))
        return new_subnet

    @lock_db.wrap_db_lock()
    def delete_subnet(self, context, id):
        orig_subnet = super(DFPlugin, self).get_subnet(context, id)
        net_id = orig_subnet['network_id']
        with context.session.begin(subtransactions=True):
            # delete subnet in DB
            super(DFPlugin, self).delete_subnet(context, id)
            network_version = version_db._update_db_version_row(
                    context.session, net_id)

        # update df controller with subnet delete
        if net_id:
            try:
                self.nb_api.delete_subnet(id, net_id,
                                          orig_subnet['tenant_id'],
                                          nw_version=network_version)
            except df_exceptions.DBKeyNotFound:
                LOG.debug("network %s is not found in DB, might have "
                          "been deleted concurrently" % net_id)

    @lock_db.wrap_db_lock()
    def create_network(self, context, network):
        with context.session.begin(subtransactions=True):
            result = super(DFPlugin, self).create_network(context,
                                                          network)
            data = network['network']
            if psec.PORTSECURITY not in data:
                data[psec.PORTSECURITY] = \
                    (psec.EXTENDED_ATTRIBUTES_2_0['networks']
                     [psec.PORTSECURITY]['default'])
            self._process_network_port_security_create(context, data, result)
            self._process_l3_create(context, result, data)
            nw_version = version_db._create_db_version_row(
                    context.session, result['id'])
        self.create_network_nb_api(context, result, nw_version)
        return result

    def create_network_nb_api(self, context, network, nw_version):
        nw_name = network.get('name', df_const.DF_NETWORK_DEFAULT_NAME)
        self.nb_api.create_lswitch(id=network['id'],
                                   topic=network['tenant_id'],
                                   name=nw_name,
                                   router_external=network['router:external'],
                                   version=nw_version,
                                   subnets=[])
        return network

    @lock_db.wrap_db_lock()
    def delete_network(self, context, network_id):
        with context.session.begin(subtransactions=True):
            network = self.get_network(context, network_id)
            tenant_id = network['tenant_id']
            super(DFPlugin, self).delete_network(context,
                                                 network_id)
            version_db._delete_db_version_row(context.session, network_id)
        # TODO(gsagie) this fix is used to remove DHCP port
        # both in the case of q-dhcp and in the case of
        # distributed virtual DHCP port created by DF
        # Need to revisit
        for port in self.nb_api.get_all_logical_ports():
            if port.get_lswitch_id() == network_id:
                try:
                    self.nb_api.delete_lport(id=port.get_id(),
                                             topic=tenant_id)
                except df_exceptions.DBKeyNotFound:
                    LOG.debug("port %s is not found in DB, might have"
                              "been deleted concurrently" % port.get_id())
        try:
            self.nb_api.delete_lswitch(id=network_id,
                                       topic=tenant_id)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("lswitch %s is not found in DF DB, might have "
                      "been deleted concurrently" % network_id)

    @lock_db.wrap_db_lock()
    def update_network(self, context, network_id, network):
        pnet._raise_if_updates_provider_attributes(network['network'])
        with context.session.begin(subtransactions=True):
            result = super(DFPlugin, self).update_network(context, network_id,
                                                          network)
            if psec.PORTSECURITY in network['network']:
                self._process_network_port_security_update(context,
                                                           network['network'],
                                                           result)
            self._process_l3_update(context, result, network['network'])
            network_version = version_db._update_db_version_row(
                    context.session, network_id)

        self.nb_api.update_lswitch(id=network_id,
                                   topic=result['tenant_id'],
                                   name=result.get(
                                           'name',
                                           df_const.DF_NETWORK_DEFAULT_NAME),
                                   router_external=result['router:external'],
                                   version=network_version)
        return result

    @lock_db.wrap_db_lock()
    def update_port(self, context, id, port):
        with context.session.begin(subtransactions=True):
            parent_name, tag = self._get_data_from_binding_profile(
                context, port['port'])
            original_port = self.get_port(context, id)
            updated_port = super(DFPlugin, self).update_port(context, id,
                                                             port)

            # TODO(yuanwei): in ML2 plugin, security_groups and
            # allow_address_pairs configuration depend on portsec switch is
            # enabled.
            if psec.PORTSECURITY in port['port']:
                self._process_port_port_security_update(
                    context, port['port'], updated_port)
            else:
                original_port_security = original_port.get(psec.PORTSECURITY)
                if original_port_security is not None:
                    updated_port[psec.PORTSECURITY] = original_port_security
                else:
                    # if the port-security-enabled field was not set in the
                    # original port, we should remain this field of the
                    # logical port in the DF DB unchanged.
                    lport = self.nb_api.get_logical_port(
                        port_id=id, topic=updated_port['tenant_id'])
                    updated_port[psec.PORTSECURITY] = \
                        lport.get_port_security_enable()

            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         updated_port)
            self.update_security_group_on_port(
                context, id, port, original_port, updated_port)

            address_pairs_updated = False
            if addr_pair.ADDRESS_PAIRS in port['port']:
                address_pairs_updated = self.update_address_pairs_on_port(
                    context, id, port, original_port, updated_port)
            if not address_pairs_updated:
                updated_port[addr_pair.ADDRESS_PAIRS] = original_port.get(
                    addr_pair.ADDRESS_PAIRS, [])

            self._update_extra_dhcp_opts_on_port(
                    context,
                    id,
                    port,
                    updated_port=updated_port)

            port_version = version_db._update_db_version_row(
                    context.session, id)

        ips = []
        if 'fixed_ips' in updated_port:
            ips = [ip['ip_address'] for ip in updated_port['fixed_ips']]

        chassis = None
        if 'binding:host_id' in updated_port:
            chassis = updated_port['binding:host_id']

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if updated_port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        updated_security_groups = updated_port.get('security_groups')
        if updated_security_groups == []:
            security_groups = None
        else:
            security_groups = updated_security_groups

        port_name = updated_port.get('name', df_const.DF_PORT_DEFAULT_NAME)
        self.nb_api.update_lport(id=updated_port['id'],
                                 topic=updated_port['tenant_id'],
                                 macs=[updated_port['mac_address']], ips=ips,
                                 name=port_name,
                                 parent_name=parent_name, tag=tag,
                                 enabled=updated_port['admin_'
                                                      'state_up'],
                                 chassis=chassis,
                                 device_owner=updated_port.get(
                                     'device_owner', None),
                                 security_groups=security_groups,
                                 port_security_enabled=updated_port[
                                     psec.PORTSECURITY],
                                 allowed_address_pairs=updated_port[
                                     addr_pair.ADDRESS_PAIRS],
                                 version=port_version)
        return updated_port

    def _get_data_from_binding_profile(self, context, port):
        if (df_const.DF_PORT_BINDING_PROFILE not in port or
                not attr.is_attr_set(
                    port[df_const.DF_PORT_BINDING_PROFILE])):
            return None, None
        parent_name = (
            port[df_const.DF_PORT_BINDING_PROFILE].get('parent_name'))
        tag = port[df_const.DF_PORT_BINDING_PROFILE].get('tag')
        if not any((parent_name, tag)):
            # An empty profile is fine.
            return None, None
        if not all((parent_name, tag)):
            # If one is set, they both must be set.
            msg = _('Invalid binding:profile. parent_name and tag are '
                    'both required.')
            raise n_exc.InvalidInput(error_message=msg)
        if not isinstance(parent_name, six.string_types):
            msg = _('Invalid binding:profile. parent_name "%s" must be '
                    'a string.') % parent_name
            raise n_exc.InvalidInput(error_message=msg)
        try:
            tag = int(tag)
            if tag < 0 or tag > 4095:
                raise ValueError
        except ValueError:
            msg = _('Invalid binding:profile. tag "%s" must be '
                    'an int between 1 and 4096, inclusive.') % tag
            raise n_exc.InvalidInput(error_message=msg)
        # Make sure we can successfully look up the port indicated by
        # parent_name.  Just let it raise the right exception if there is a
        # problem.
        self.get_port(context, parent_name)
        return parent_name, tag

    def _determine_port_security(self, context, port):
        """Returns a boolean (port_security_enabled).

        Port_security is the value associated with the port if one is present
        otherwise the value associated with the network is returned.
        """
        if port.get('device_owner') and utils.is_port_trusted(port):
            return False

        if attr.is_attr_set(port.get(psec.PORTSECURITY)):
            port_security_enabled = port[psec.PORTSECURITY]
        else:
            port_security_enabled = self._get_network_security_binding(
                context, port['network_id'])

        return port_security_enabled

    @lock_db.wrap_db_lock()
    def create_port(self, context, port):
        with context.session.begin(subtransactions=True):
            parent_name, tag = self._get_data_from_binding_profile(
                context, port['port'])
            dhcp_opts = port['port'].get(edo_ext.EXTRADHCPOPTS, [])
            db_port = super(DFPlugin, self).create_port(context, port)
            # TODO(yuanwei): in ML2 plugin, security_groups and
            # allow_address_pairs configuration depend on portsec switch is
            # enabled.
            portsec_tmp = {
                psec.PORTSECURITY:
                    self._determine_port_security(context, port['port'])
            }
            self._process_port_port_security_create(context, portsec_tmp,
                                                    db_port)

            sgids = self._get_security_groups_on_port(context, port)
            self._process_port_create_security_group(context, db_port,
                                                     sgids)
            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         db_port)

            db_port[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL
            if (df_const.DF_PORT_BINDING_PROFILE in port['port'] and
                    attr.is_attr_set(
                        port['port'][df_const.DF_PORT_BINDING_PROFILE])):
                db_port[df_const.DF_PORT_BINDING_PROFILE] = (
                    port['port'][df_const.DF_PORT_BINDING_PROFILE])
            db_port[addr_pair.ADDRESS_PAIRS] = (
                self._process_create_allowed_address_pairs(
                    context, db_port,
                    port['port'].get(addr_pair.ADDRESS_PAIRS)))
            self._process_port_create_extra_dhcp_opts(context, db_port,
                                                      dhcp_opts)
            port_version = version_db._create_db_version_row(
                    context.session, db_port['id'])
        # This extra lookup is necessary to get the latest db model
        # for the extension functions.
        port_model = self._get_port(context, db_port['id'])
        self._apply_dict_extend_functions('ports', db_port, port_model)

        return self.create_port_in_nb_api(db_port, parent_name,
                                          tag, port_version)

    def create_port_in_nb_api(self, port, parent_name, tag, port_version):
        # The port name *must* be port['id'].  It must match the iface-id set
        # in the Interfaces table of the Open_vSwitch database, which nova sets
        # to be the port ID.
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
        if port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        security_groups = port.get('security_groups')
        if security_groups == []:
            sgs = None
        else:
            sgs = security_groups

        self.nb_api.create_lport(
            id=port['id'],
            lswitch_id=port['network_id'],
            topic=port['tenant_id'],
            macs=[port['mac_address']], ips=ips,
            name=port.get('name', df_const.DF_PORT_DEFAULT_NAME),
            parent_name=parent_name, tag=tag,
            enabled=port.get('admin_state_up', None),
            chassis=chassis, tunnel_key=tunnel_key,
            version=port_version,
            device_owner=port.get('device_owner', None),
            security_groups=sgs,
            port_security_enabled=port[psec.PORTSECURITY],
            allowed_address_pairs=port[addr_pair.ADDRESS_PAIRS])

        return port

    def _pre_delete_port(self, port, port_check):
        """Do some preliminary operations before deleting the port."""
        LOG.debug("Deleting port %s", port['id'])
        if not port_check:
            return

        if port['device_owner'] in ['network:router_interface',
                                    'network:router_gateway',
                                    'network:floatingip']:
            fixed_ips = port['fixed_ips']
            if fixed_ips:
                reason = _('has device owner %s') % port['device_owner']
                raise n_exc.ServicePortInUse(port_id=port['id'],
                                             reason=reason)
            else:
                LOG.debug("Port %(port_id)s has owner %(port_owner)s, but "
                          "no IP address, so it can be deleted",
                          {'port_id': port['id'],
                           'port_owner': port['device_owner']})

    @lock_db.wrap_db_lock()
    def delete_port(self, context, port_id, l3_port_check=True):
        port = self.get_port(context, port_id)
        self._pre_delete_port(port, l3_port_check)
        topic = port['tenant_id']

        with context.session.begin(subtransactions=True):
            self.disassociate_floatingips(context, port_id)
            super(DFPlugin, self).delete_port(context, port_id)
            version_db._delete_db_version_row(context.session, port_id)

        try:
            self.nb_api.delete_lport(id=port_id, topic=topic)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("port %s is not found in DF DB, might have "
                      "been deleted concurrently" % port_id)

    def extend_port_dict_binding(self, port_res, port_db):
        super(DFPlugin, self).extend_port_dict_binding(port_res, port_db)
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL

    def _create_router_db(self, context, router, tenant_id):
        """Create a router db object with dvr additions."""
        router['distributed'] = is_distributed_router(router)
        with context.session.begin(subtransactions=True):
            router_db = super(
                DFPlugin, self)._create_router_db(
                    context, router, tenant_id)
            self._process_extra_attr_router_create(context, router_db, router)
            return router_db

    @lock_db.wrap_db_lock()
    def create_router(self, context, router):
        with context.session.begin(subtransactions=True):
            router = super(DFPlugin, self).create_router(
                context, router)
            router_version = version_db._create_db_version_row(
                    context.session, router['id'])

        router_id = router['id']
        tenant_id = router['tenant_id']
        is_distributed = router.get('distributed', False)
        router_name = router.get('name', df_const.DF_ROUTER_DEFAULT_NAME)
        self.nb_api.create_lrouter(router_id, topic=tenant_id,
                                   name=router_name,
                                   distributed=is_distributed,
                                   version=router_version,
                                   ports=[])
        return router

    @lock_db.wrap_db_lock()
    def delete_router(self, context, router_id):
        router = self.get_router(context, router_id)
        with context.session.begin(subtransactions=True):
            ret_val = super(DFPlugin, self).delete_router(context,
                                                          router_id)
            version_db._delete_db_version_row(context.session, router_id)
        try:
            self.nb_api.delete_lrouter(id=router_id,
                                       topic=router['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB, might have "
                      "been deleted concurrently" % router_id)
        return ret_val

    @lock_db.wrap_db_lock()
    def add_router_interface(self, context, router_id, interface_info):
        add_by_port, add_by_sub = self._validate_interface_info(
            interface_info)
        if add_by_sub:
            subnet = self.get_subnet(context, interface_info['subnet_id'])
            port = {'port': {'tenant_id': subnet['tenant_id'],
                             'network_id': subnet['network_id'], 'name': '',
                             'admin_state_up': True, 'device_id': '',
                             'device_owner': l3_db.DEVICE_OWNER_ROUTER_INTF,
                             'mac_address': attr.ATTR_NOT_SPECIFIED,
                             'fixed_ips': [{'subnet_id': subnet['id'],
                                            'ip_address':
                                                subnet['gateway_ip']}]}}
            port = self.create_port(context, port)
        elif add_by_port:
            port = self.get_port(context, interface_info['port_id'])
            subnet_id = port['fixed_ips'][0]['subnet_id']
            subnet = self.get_subnet(context, subnet_id)

        lswitch_id = subnet['network_id']
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))

        logical_port = self.nb_api.get_logical_port(port['id'],
                                                    port['tenant_id'])

        interface_info['port_id'] = port['id']
        if 'subnet_id' in interface_info:
            del interface_info['subnet_id']

        with context.session.begin(subtransactions=True):
            result = super(DFPlugin, self).add_router_interface(
                context, router_id, interface_info)
            router_version = version_db._update_db_version_row(
                    context.session, router_id)

        self.nb_api.add_lrouter_port(port['id'],
                                     router_id, lswitch_id,
                                     port['tenant_id'],
                                     router_version=router_version,
                                     mac=port['mac_address'],
                                     network=network,
                                     tunnel_key=logical_port.get_tunnel_key())
        return result

    @lock_db.wrap_db_lock()
    def remove_router_interface(self, context, router_id, interface_info):
        with context.session.begin(subtransactions=True):
            new_router = super(DFPlugin, self).remove_router_interface(
                context, router_id, interface_info)
            router_version = version_db._update_db_version_row(
                    context.session, router_id)

        subnet = self.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        try:
            self.nb_api.delete_lrouter_port(router_id,
                                            network_id,
                                            subnet['tenant_id'],
                                            router_version=router_version)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("logical router %s is not found in DF DB, "
                      "suppressing delete_lrouter_port "
                      "exception" % router_id)
        return new_router

    def _create_dhcp_server_port(self, context, subnet):
        """Create and return dhcp port information.

        If an expected failure occurs, a None port is returned.

        """
        port = {'port': {'tenant_id': context.tenant_id,
                         'network_id': subnet['network_id'], 'name': '',
                         'binding:host_id': (
                             df_common_const.DRAGONFLOW_VIRTUAL_PORT),
                         'admin_state_up': True, 'device_id': '',
                         'device_owner': const.DEVICE_OWNER_DHCP,
                         'mac_address': attr.ATTR_NOT_SPECIFIED,
                         'fixed_ips': [{'subnet_id': subnet['id']}]}}
        port = self.create_port(context, port)

        return port

    def _get_ports_by_subnet_and_owner(self, context, subnet_id, device_owner):
        """Used to get all port in a subnet by the device owner"""
        LOG.debug("Dragonflow : subnet_id: %s", subnet_id)
        filters = {'fixed_ips': {'subnet_id': [subnet_id]},
                   'device_owner': [const.DEVICE_OWNER_DHCP]}
        return self.get_ports(context, filters=filters)

    def _get_dhcp_port_for_subnet(self, context, subnet_id):
        ports = self._get_ports_by_subnet_and_owner(
                context,
                subnet_id,
                const.DEVICE_OWNER_DHCP)
        try:
            return ports[0]
        except IndexError:
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

    def _update_subnet_dhcp_centralized(self, context, subnet):
        """Update the dhcp configration for the subnet

        Returns the dhcp server ip address if configured
        """
        if subnet['enable_dhcp']:
            port = self._get_dhcp_port_for_subnet(
                    context,
                    subnet['id'])
            return self._get_ip_from_port(port)
        else:
            return subnet['allocation_pools'][0]['start']

    def _update_subnet_dhcp(self, context, old_subnet, new_subnet):
        """Update the dhcp configration for.

        Returns the dhcp server port if configured
        """
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            return self._update_subnet_dhcp_centralized(context, new_subnet)

        if old_subnet['enable_dhcp']:
            port = self._get_dhcp_port_for_subnet(
                    context,
                    old_subnet['id'])
        if not new_subnet['enable_dhcp']:
            if old_subnet['enable_dhcp']:
                if port:
                    self.delete_port(context, port['id'])
            return None
        if new_subnet['enable_dhcp'] and not old_subnet['enable_dhcp']:
            port = self._create_dhcp_server_port(context, new_subnet)

        return port

    def _handle_create_subnet_dhcp(self, context, subnet):
        """Create the dhcp configration for the subnet

        Returns the dhcp server port if configured
        """
        if subnet['enable_dhcp']:
            if cfg.CONF.df.use_centralized_ipv6_DHCP:
                return subnet['allocation_pools'][0]['start']
            else:
                dhcp_port = self._create_dhcp_server_port(context, subnet)
                return dhcp_port
        return None

    def _get_floatingip_port(self, context, floatingip_id):
        filters = {'device_id': [floatingip_id]}
        floating_ports = self.get_ports(context, filters=filters)
        if floating_ports:
            return floating_ports[0]
        return None

    def _get_floatingip_subnet(self, context, subnet_id):
        gateway_subnet = self.get_subnet(context, subnet_id)
        if gateway_subnet['ip_version'] == 4:
            return gateway_subnet
        return None

    @lock_db.wrap_db_lock()
    def create_floatingip(self, context, floatingip):
        try:
            floatingip_port = None
            with context.session.begin(subtransactions=True):
                floatingip_dict = super(DFPlugin, self).create_floatingip(
                    context, floatingip,
                    initial_status=const.FLOATINGIP_STATUS_DOWN)

                floatingip_port = self._get_floatingip_port(
                    context, floatingip_dict['id'])
                if not floatingip_port:
                    raise n_exc.DeviceNotFoundError(
                        device_name=floatingip_dict['id'])
                subnet_id = floatingip_port['fixed_ips'][0]['subnet_id']
                floatingip_subnet = self._get_floatingip_subnet(
                    context, subnet_id)
                if floatingip_subnet is None:
                    raise n_exc.SubnetNotFound(subnet_id=subnet_id)
                fip_version = version_db._create_db_version_row(
                        context.session, floatingip_dict['id'])
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = True
                # delete the stale floatingip port
                try:
                    if floatingip_port:
                        self.nb_api.delete_lport(floatingip_port['id'],
                                                 floatingip_port['tenant_id'])
                except df_exceptions.DBKeyNotFound:
                    pass

        self.nb_api.create_floatingip(
                id=floatingip_dict['id'],
                topic=floatingip_dict['tenant_id'],
                name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
                floating_ip_address=floatingip_dict['floating_ip_address'],
                floating_network_id=floatingip_dict['floating_network_id'],
                router_id=floatingip_dict['router_id'],
                port_id=floatingip_dict['port_id'],
                fixed_ip_address=floatingip_dict['fixed_ip_address'],
                status=floatingip_dict['status'],
                floating_port_id=floatingip_port['id'],
                floating_mac_address=floatingip_port['mac_address'],
                external_gateway_ip=floatingip_subnet['gateway_ip'],
                version=fip_version,
                external_cidr=floatingip_subnet['cidr'])

        return floatingip_dict

    @lock_db.wrap_db_lock()
    def update_floatingip(self, context, id, floatingip):
        with context.session.begin(subtransactions=True):
            floatingip_dict = super(DFPlugin, self).update_floatingip(
                context, id, floatingip)
            fip_version = version_db._update_db_version_row(
                    context.session, id)

        self.nb_api.update_floatingip(
            id=floatingip_dict['id'],
            topic=floatingip_dict['tenant_id'],
            notify=True,
            name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
            router_id=floatingip_dict['router_id'],
            port_id=floatingip_dict['port_id'],
            version=fip_version,
            fixed_ip_address=floatingip_dict['fixed_ip_address'],
            status=floatingip_dict['status'])
        return floatingip_dict

    @lock_db.wrap_db_lock()
    def delete_floatingip(self, context, id):
        with context.session.begin(subtransactions=True):
            floatingip = self.get_floatingip(context, id)
            super(DFPlugin, self).delete_floatingip(context, id)
            version_db._delete_db_version_row(context.session, id)

        try:
            self.nb_api.delete_floatingip(id=id,
                                          topic=floatingip['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("floatingip %s is not found in DF DB, might have "
                      "been deleted concurrently" % id)

    def get_floatingip(self, context, id, fields=None):
        with context.session.begin(subtransactions=True):
            fip = super(DFPlugin, self).get_floatingip(context, id, fields)
            fip['status'] = self.nb_api.get_floatingip(id).get_status()
            return fip


def is_distributed_router(router):
    """Return True if router to be handled is distributed."""
    try:
        # See if router is a DB object first
        requested_router_type = router.extra_attributes.distributed
    except AttributeError:
        # if not, try to see if it is a request body
        requested_router_type = router.get('distributed')
    if attr.is_attr_set(requested_router_type):
        return requested_router_type
    return cfg.CONF.router_distributed
