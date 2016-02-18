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
from neutron.extensions import extra_dhcp_opt as edo_ext
from neutron.extensions import portbindings
from neutron.extensions import providernet as pnet

from neutron.common import constants as const
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import agents_db
from neutron.db import agentschedulers_db
from neutron.db import api as db_api
from neutron.db import db_base_plugin_v2
from neutron.db import external_net_db
from neutron.db import extradhcpopt_db
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_db
from neutron.db import l3_gwmode_db
from neutron.db import portbindings_db
from neutron.db import securitygroups_db

from dragonflow._i18n import _, _LE, _LI
from dragonflow.common import common_params
from dragonflow.common import constants as df_common_const
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db.neutron import versionedobjects_db as vo_db
from dragonflow.neutron.common import constants as df_const

LOG = log.getLogger(__name__)

cfg.CONF.register_opts(common_params.df_opts, 'df')


class DFPlugin(db_base_plugin_v2.NeutronDbPluginV2,
               securitygroups_db.SecurityGroupDbMixin,
               l3_agentschedulers_db.L3AgentSchedulerDbMixin,
               l3_gwmode_db.L3_NAT_db_mixin,
               external_net_db.External_net_db_mixin,
               portbindings_db.PortBindingMixin,
               extradhcpopt_db.ExtraDhcpOptMixin,
               extraroute_db.ExtraRoute_db_mixin,
               agentschedulers_db.DhcpAgentSchedulerDbMixin):

    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    supported_extension_aliases = ["quotas",
                                   "extra_dhcp_opt",
                                   "binding",
                                   "agent",
                                   "dhcp_agent_scheduler",
                                   "security-group",
                                   "extraroute",
                                   "external-net",
                                   "router"]

    def __init__(self):
        super(DFPlugin, self).__init__()
        LOG.info(_LI("Starting DFPlugin"))
        self.vif_type = portbindings.VIF_TYPE_OVS
        self._set_base_port_binding()
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        registry.subscribe(self.post_fork_initialize, resources.PROCESS,
                           events.AFTER_CREATE)
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)

        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=True)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

        self._setup_dhcp()
        self._start_rpc_notifiers()

    def post_fork_initialize(self, resource, event, trigger, **kwargs):
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
        self.conn = n_rpc.create_connection(new=True)
        self.conn.create_consumer(topics.PLUGIN, self.endpoints, fanout=False)
        self.conn.create_consumer(topics.L3PLUGIN, self.endpoints,
                                  fanout=False)
        self.conn.create_consumer(topics.REPORTS,
                                  [agents_db.AgentExtRpcCallback()],
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

    def create_security_group(self, context, security_group,
                              default_sg=False):
        with db_api.autonested_transaction(context.session):
            sg_db = super(DFPlugin,
                          self).create_security_group(context, security_group,
                                                      default_sg)
            vo_db.create_version(context,
                                 sg_db.get('id'),
                                 df_common_const.VERSIONED_SECURITY_GROUP)
            lock_db.create_lock(context, sg_db.get('id'))

        sg_name = sg_db['id']
        rules = sg_db.get('security_group_rules')

        nb_lock = lock_db.DFDBLock(context, sg_db.get('id'))
        with nb_lock:
            self.nb_api.create_security_group(name=sg_name, rules=rules)
        return sg_db

    def create_security_group_rule(self, context, security_group_rule):
        with db_api.autonested_transaction(context.session):
            sg_rule = super(DFPlugin, self).create_security_group_rule(
                context, security_group_rule)
            sg_id = sg_rule['security_group_id']

        old_version = vo_db.increment_version(context, sg_id)

        if sg_rule and sg_id:
            nb_lock = lock_db.DFDBLock(context, sg_id)
            with nb_lock:
                self.nb_api.add_security_group_rules(sg_id, old_version,
                                                     [sg_rule])
        return sg_rule

    def delete_security_group_rule(self, context, id):
        security_group_rule = self.get_security_group_rule(context, id)
        sg_id = security_group_rule['security_group_id']

        if sg_id:
            with db_api.autonested_transaction(context.session):
                super(DFPlugin, self).delete_security_group_rule(context, id)

            old_version = vo_db.increment_version(context, sg_id)

            nb_lock = lock_db.DFDBLock(context, sg_id)
            with nb_lock:
                self.nb_api.delete_security_group_rule(sg_id, old_version, id)

    def delete_security_group(self, context, sg_id):
        with db_api.autonested_transaction(context.session):
            sg_db = super(DFPlugin, self).delete_security_group(context,
                                                                sg_id)
            vo_db.delete_version(context, oid=sg_id)

        nb_lock = lock_db.DFDBLock(context, sg_id)
        with nb_lock:
            self.nb_api.delete_security_group(sg_id)

        with db_api.autonested_transaction(context.session):
            lock_db.delete_lock(context, oid=sg_id)
        return sg_db

    def create_subnet(self, context, subnet):
        with db_api.autonested_transaction(context.session):
            # create subnet in DB
            new_subnet = super(DFPlugin,
                               self).create_subnet(context, subnet)
            net_id = new_subnet['network_id']
            dhcp_address = self._handle_create_subnet_dhcp(
                                context,
                                new_subnet)

        old_version = vo_db.increment_version(context, net_id)

        if new_subnet and net_id and dhcp_address:
            # update df controller with subnet
            nb_lock = lock_db.DFDBLock(context, net_id)
            with nb_lock:
                self.nb_api.add_subnet(
                    new_subnet['id'],
                    net_id,
                    old_version,
                    enable_dhcp=new_subnet['enable_dhcp'],
                    cidr=new_subnet['cidr'],
                    dhcp_ip=dhcp_address,
                    gateway_ip=new_subnet['gateway_ip'],
                    dns_nameservers=new_subnet.get('dns_nameservers', []))
        return new_subnet

    def update_subnet(self, context, id, subnet):
        with db_api.autonested_transaction(context.session):
            # update subnet in DB
            original_subnet = super(DFPlugin, self).get_subnet(context, id)
            new_subnet = super(DFPlugin,
                               self).update_subnet(context, id, subnet)
            net_id = new_subnet['network_id']
            dhcp_address = self._update_subnet_dhcp(
                    context,
                    original_subnet,
                    new_subnet)

        old_version = vo_db.increment_version(context, net_id)

        if new_subnet and net_id and dhcp_address:
            # update df controller with subnet
            nb_lock = lock_db.DFDBLock(context, net_id)
            with nb_lock:
                self.nb_api.update_subnet(
                    new_subnet['id'],
                    net_id,
                    old_version,
                    enable_dhcp=new_subnet['enable_dhcp'],
                    cidr=new_subnet['cidr'],
                    dhcp_ip=dhcp_address,
                    gateway_ip=new_subnet['gateway_ip'],
                    dns_nameservers=new_subnet.get('dns_nameservers', []))
        return new_subnet

    def delete_subnet(self, context, id):
        orig_subnet = super(DFPlugin, self).get_subnet(context, id)
        net_id = orig_subnet['network_id']
        with db_api.autonested_transaction(context.session):
            # delete subnet in DB
            super(DFPlugin, self).delete_subnet(context, id)

        old_version = vo_db.increment_version(context, net_id)

        # update df controller with subnet delete
        if net_id:
            nb_lock = lock_db.DFDBLock(context, net_id)
            with nb_lock:
                try:
                    self.nb_api.delete_subnet(id, net_id, old_version)
                except df_exceptions.DBKeyNotFound:
                    LOG.debug("network %s is not found in DB, might have "
                              "been deleted concurrently" % net_id)

    def create_network(self, context, network):
        with db_api.autonested_transaction(context.session):
            result = super(DFPlugin, self).create_network(context,
                                                          network)
            self._process_l3_create(context, result, network['network'])
            net_id = result.get('id')
            vo_db.create_version(context,
                                 net_id,
                                 df_common_const.VERSIONED_NETWORK)
            lock_db.create_lock(context, net_id)

        if result and net_id:
            nb_lock = lock_db.DFDBLock(context, net_id)
            with nb_lock:
                self.create_network_nb_api(context, result)
        return result

    def create_network_nb_api(self, context, network):
        external_ids = {df_const.DF_NETWORK_NAME_EXT_ID_KEY: network['name']}

        # TODO(DF): Undo logical switch creation on failure
        self.nb_api.create_lswitch(name=network['id'],
                                   topic=network['tenant_id'],
                                   external_ids=external_ids,
                                   subnets=[])
        return network

    def delete_network(self, context, network_id):
        with db_api.autonested_transaction(context.session):
            network = self.get_network(context, network_id)
            tenant_id = network['tenant_id']
            super(DFPlugin, self).delete_network(context,
                                                 network_id)
            vo_db.delete_version(context, oid=network_id)

        nb_lock = lock_db.DFDBLock(context, network_id)
        with nb_lock:
            # TODO(gsagie) this fix is used to remove DHCP port
            # both in the case of q-dhcp and in the case of
            # distributed virtual DHCP port created by DF
            # Need to revisit
            for port in self.nb_api.get_all_logical_ports():
                if port.get_lswitch_id() == network_id:
                    try:
                        self.nb_api.delete_lport(name=port.get_id(),
                                                 topic=tenant_id)
                    except df_exceptions.DBKeyNotFound:
                        LOG.debug("port %s is not found in DB, might have"
                                  "been deleted concurrently" % port.get_id())
            try:
                self.nb_api.delete_lswitch(name=network_id,
                                           topic=tenant_id)
            except df_exceptions.DBKeyNotFound:
                LOG.debug("lswitch %s is not found in DF DB, might have "
                          "been deleted concurrently" % network_id)

        with db_api.autonested_transaction(context.session):
            lock_db.delete_lock(context, oid=network_id)

    def _set_network_name(self, context, network_id, name, old_version):
        ext_id = [df_const.DF_NETWORK_NAME_EXT_ID_KEY, name]
        self.nb_api.update_lswitch(name=network_id,
                                   old_version=old_version,
                                   external_ids=ext_id)

    def update_network(self, context, network_id, network):
        pnet._raise_if_updates_provider_attributes(network['network'])
        # TODO(gsagie) rollback needed
        with db_api.autonested_transaction(context.session):
            result = super(DFPlugin, self).update_network(context, network_id,
                                                          network)
            self._process_l3_update(context, result, network['network'])

        old_version = vo_db.increment_version(context, network_id)

        if 'name' in network['network']:
            nb_lock = lock_db.DFDBLock(context, network_id)
            with nb_lock:
                self._set_network_name(context, network_id,
                                       network['network']['name'],
                                       old_version)
        return result

    def update_port(self, context, id, port):
        with db_api.autonested_transaction(context.session):
            parent_name, tag = self._get_data_from_binding_profile(
                context, port['port'])
            original_port = self.get_port(context, id)
            updated_port = super(DFPlugin, self).update_port(context, id,
                                                             port)

            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         updated_port)
            self.update_security_group_on_port(
                context, id, port, original_port, updated_port)

            self._update_extra_dhcp_opts_on_port(
                    context,
                    id,
                    port,
                    updated_port=updated_port)

        old_version = vo_db.increment_version(context, updated_port['id'])

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
        if updated_port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        updated_security_groups = updated_port.get('security_groups')
        if updated_security_groups == []:
            security_groups = None
        else:
            security_groups = updated_security_groups

        nb_lock = lock_db.DFDBLock(context, updated_port['id'])
        with nb_lock:
            self.nb_api.update_lport(name=updated_port['id'],
                                     old_version=old_version,
                                     macs=[updated_port['mac_address']],
                                     ips=ips,
                                     external_ids=external_ids,
                                     parent_name=parent_name, tag=tag,
                                     enabled=updated_port['admin_state_up'],
                                     port_security=allowed_macs,
                                     chassis=chassis,
                                     device_owner=updated_port.get(
                                         'device_owner', None),
                                     security_groups=security_groups)
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

    def _get_allowed_mac_addresses_from_port(self, port):
        allowed_macs = set()
        allowed_macs.add(port['mac_address'])
        allowed_address_pairs = port.get('allowed_address_pairs', [])
        for allowed_address in allowed_address_pairs:
            allowed_macs.add(allowed_address['mac_address'])
        return list(allowed_macs)

    def create_port(self, context, port):
        with db_api.autonested_transaction(context.session):
            parent_name, tag = self._get_data_from_binding_profile(
                context, port['port'])
            dhcp_opts = port['port'].get(edo_ext.EXTRADHCPOPTS, [])
            db_port = super(DFPlugin, self).create_port(context, port)
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
            self._process_port_create_extra_dhcp_opts(context, db_port,
                                                      dhcp_opts)
            vo_db.create_version(context,
                                 db_port['id'],
                                 df_common_const.VERSIONED_PORT)
            lock_db.create_lock(context, db_port['id'])

        nb_lock = lock_db.DFDBLock(context, db_port['id'])
        with nb_lock:
            self.create_port_in_nb_api(context, db_port, parent_name,
                                       tag, sgids)
        return db_port

    def create_port_in_nb_api(self, context, port, parent_name, tag, sgids):
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
        if port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        self.nb_api.create_lport(
            name=port['id'],
            lswitch_name=port['network_id'],
            topic=port['tenant_id'],
            macs=[port['mac_address']], ips=ips,
            external_ids=external_ids,
            parent_name=parent_name, tag=tag,
            enabled=port.get('admin_state_up', None),
            chassis=chassis, tunnel_key=tunnel_key,
            port_security=allowed_macs,
            device_owner=port.get('device_owner', None),
            sgids=sgids)

        return port

    def _pre_delete_port(self, context, port_id, port_check):
        """Do some preliminary operations before deleting the port."""
        LOG.debug("Deleting port %s", port_id)
        if not port_check:
            return
        try:
            port = self.get_port(context, port_id)
        except n_exc.PortNotFound:
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

    def delete_port(self, context, port_id, l3_port_check=True):
        self._pre_delete_port(context, port_id, l3_port_check)
        try:
            port = self.get_port(context, port_id)
            topic = port['tenant_id']

            nb_lock = lock_db.DFDBLock(context, port_id)
            with nb_lock:
                self.nb_api.delete_lport(name=port_id, topic=topic)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("port %s is not found in DF DB, might have "
                      "been deleted concurrently" % port_id)

        with db_api.autonested_transaction(context.session):
            self.disassociate_floatingips(context, port_id)
            super(DFPlugin, self).delete_port(context, port_id)
            vo_db.delete_version(context, oid=port_id)
            lock_db.delete_lock(context, oid=port_id)

    def extend_port_dict_binding(self, port_res, port_db):
        super(DFPlugin, self).extend_port_dict_binding(port_res, port_db)
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL

    def create_router(self, context, router):
        with db_api.autonested_transaction(context.session):
            router = super(DFPlugin, self).create_router(
                context, router)
            vo_db.create_version(context,
                                 router['id'],
                                 df_common_const.VERSIONED_ROUTER)
            lock_db.create_lock(context, router['id'])

        router_name = router['id']
        tenant_id = router['tenant_id']
        external_ids = {df_const.DF_ROUTER_NAME_EXT_ID_KEY:
                        router.get('name', 'no_router_name')}

        nb_lock = lock_db.DFDBLock(context, router['id'])
        with nb_lock:
            self.nb_api.create_lrouter(name=router_name,
                                       topic=tenant_id,
                                       external_ids=external_ids,
                                       ports=[])
        return router

    def delete_router(self, context, router_id):
        router_name = router_id
        router = self.get_router(context, router_id)
        nb_lock = lock_db.DFDBLock(context, router_id)
        with nb_lock:
            try:
                self.nb_api.delete_lrouter(name=router_name,
                                           topic=router['tenant_id'])
            except df_exceptions.DBKeyNotFound:
                LOG.debug("router %s is not found in DF DB, might have "
                          "been deleted concurrently" % router_name)

        with db_api.autonested_transaction(context.session):
            ret_val = super(DFPlugin, self).delete_router(context,
                                                          router_id)
            vo_db.delete_version(context, oid=router_id)
            lock_db.delete_lock(context, oid=router_id)
        return ret_val

    def add_router_interface(self, context, router_id, interface_info):
        add_by_port, add_by_sub = self._validate_interface_info(
            interface_info)
        if add_by_sub:
            subnet = self.get_subnet(context, interface_info['subnet_id'])
            port = {'port': {'tenant_id': context.tenant_id,
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

        lrouter = router_id
        lswitch = subnet['network_id']
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))
        interface_info['port_id'] = port['id']
        if 'subnet_id' in interface_info:
            del interface_info['subnet_id']

        with db_api.autonested_transaction(context.session):
            result = super(DFPlugin, self).add_router_interface(
                context, router_id, interface_info)

        old_version = vo_db.increment_version(context, router_id)

        nb_lock = lock_db.DFDBLock(context, router_id)
        with nb_lock:
            lport = self.nb_api.get_logical_port(port['id'])
            self.nb_api.add_lrouter_port(port['id'],
                                         lrouter, old_version, lswitch,
                                         mac=port['mac_address'],
                                         network=network,
                                         tunnel_key=lport.get_tunnel_key())
        return result

    def remove_router_interface(self, context, router_id, interface_info):
        with db_api.autonested_transaction(context.session):
            new_router = super(DFPlugin, self).remove_router_interface(
                context, router_id, interface_info)

        old_version = vo_db.increment_version(context, router_id)

        subnet = self.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        nb_lock = lock_db.DFDBLock(context, router_id)
        with nb_lock:
            try:
                self.nb_api.delete_lrouter_port(router_id, old_version,
                                                network_id)
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

        Returns the dhcp server ip address if configured
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

        return self._get_ip_from_port(port)

    def _handle_create_subnet_dhcp(self, context, subnet):
        """Create the dhcp configration for the subnet

        Returns the dhcp server ip address if configured
        """
        if subnet['enable_dhcp']:
            if cfg.CONF.df.use_centralized_ipv6_DHCP:
                return subnet['allocation_pools'][0]['start']
            else:
                dhcp_port = self._create_dhcp_server_port(context, subnet)
                return self._get_ip_from_port(dhcp_port)
        return None
