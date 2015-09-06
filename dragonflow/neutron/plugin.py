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
from oslo_db import api as oslo_db_api
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
from neutron.extensions import securitygroup as sec_grp
from neutron.i18n import _, _LE, _LI

from dragonflow.common import common_params
from dragonflow.db import api_nb
from dragonflow.neutron.common import constants as ovn_const
from dragonflow.neutron.common import utils

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
                                   "security-group",
                                   "extraroute",
                                   "external-net",
                                   "router"]

    def __init__(self):
        super(DFPlugin, self).__init__()
        LOG.info(_LI("Starting DFPlugin"))
        self.vif_type = portbindings.VIF_TYPE_OVS
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}

        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(nb_driver_class())
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

        self.global_id = self._find_current_global_id()

        self.base_binding_dict = {
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
            portbindings.VIF_DETAILS: {
                # TODO(rkukura): Replace with new VIF security details
                portbindings.CAP_PORT_FILTER:
                'security-group' in self.supported_extension_aliases}}

        self._setup_rpc()

    def _find_current_global_id(self):
        # TODO(gsagie) This method finds the biggest allocated id in the DB
        # and continue to allocate starting from it, we still need to handle
        # the case of wrap up in the id's
        max_id = 0
        try:
            for port in self.nb_api.get_all_logical_ports():
                if port.get_tunnel_key() > max_id:
                    max_id = port.get_tunnel_key()
        except Exception:
            pass
        return max_id

    def _setup_rpc(self):
        self.conn = n_rpc.create_connection(new=True)
        self.endpoints = [dhcp_rpc.DhcpRpcCallback(),
                          l3_rpc.L3RpcCallback(),
                          agents_db.AgentExtRpcCallback(),
                          metadata_rpc.MetadataRpcCallback()]
        self.agent_notifiers[const.AGENT_TYPE_L3] = (
            l3_rpc_agent_api.L3AgentNotifyAPI()
        )
        self.agent_notifiers[const.AGENT_TYPE_DHCP] = (
            dhcp_rpc_agent_api.DhcpAgentNotifyAPI())
        self.network_scheduler = importutils.import_object(
            cfg.CONF.network_scheduler_driver
        )
        self.supported_extension_aliases.extend(
            ['agent', 'dhcp_agent_scheduler'])
        self.conn.create_consumer(topics.PLUGIN, self.endpoints,
                                  fanout=False)
        self.conn.create_consumer(topics.L3PLUGIN, self.endpoints,
                                  fanout=False)
        self.conn.consume_in_threads()

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

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_security_group(self, context, security_group,
                              default_sg=False):
        sg = security_group.get('security_group')
        tenant_id = self._get_tenant_id_for_create(context, sg)
        if not default_sg:
            self._ensure_default_security_group(context, tenant_id)

        with context.session.begin(subtransactions=True):
            sg_db = super(DFPlugin,
                          self).create_security_group(context,
                                                      security_group,
                                                      default_sg)
            self.nb_api.create_security_group(sg_db['id'], rules=[])
            return sg_db

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_security_group_rule(self, context, security_group_rule):
        bulk_rule = {'security_group_rules': [security_group_rule]}
        return self.create_security_group_rule_bulk(context, bulk_rule)[0]

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_security_group_rule_bulk(self, context, security_group_rules):
        sg_id = self._validate_security_group_rules(context,
                                                    security_group_rules)

        # Check to make sure security group exists
        security_group = super(DFPlugin,
                               self).get_security_group(context,
                                                        sg_id)
        if not security_group:
            raise sec_grp.SecurityGroupNotFound(id=sg_id)

        with context.session.begin(subtransactions=True):
            new_rule_list = super(DFPlugin,
                                  self).create_security_group_rule_bulk_native(
                context, security_group_rules)
            self.nb_api.add_security_group_rules(sg_id, new_rule_list)
            return new_rule_list

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_security_group_rule(self, context, sgr_id):
        rule_db = self._get_security_group_rule(context, sgr_id)
        security_group_id = rule_db['security_group_id']
        with context.session.begin(subtransactions=True):
            super(DFPlugin,
                  self).delete_security_group_rule(context, sgr_id)
            self.nb_api.delete_security_group_rule(security_group_id, sgr_id)

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_security_group(self, context, sg_id):
        sg = super(DFPlugin, self).get_security_group(
            context, sg_id)
        if not sg:
            raise sec_grp.SecurityGroupNotFound(id=sg_id)

        if sg['name'] == 'default' and not context.is_admin:
            raise sec_grp.SecurityGroupCannotRemoveDefault()

        with context.session.begin(subtransactions=True):
            sg_db = super(DFPlugin, self).delete_security_group(context,
                                                                sg_id)
            self.nb_api.delete_security_group(sg_id)
            return sg_db

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_subnet(self, context, subnet):
        with context.session.begin(subtransactions=True):
            # create subnet in DB
            new_subnet = super(DFPlugin,
                               self).create_subnet(context, subnet)
            net_id = new_subnet['network_id']
            # update df controller with subnet
            self.nb_api.add_subnet(
                new_subnet['id'],
                utils.ovn_name(net_id),
                enable_dhcp=new_subnet['enable_dhcp'],
                cidr=new_subnet['cidr'],
                dhcp_ip=new_subnet['allocation_pools'][0]['start'],
                gateway_ip=new_subnet['gateway_ip'],
                dns_nameservers=new_subnet.get('dns_nameservers', []))

        return new_subnet

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def update_subnet(self, context, id, subnet):
        with context.session.begin(subtransactions=True):
            # update subnet in DB
            new_subnet = super(DFPlugin,
                               self).update_subnet(context, id, subnet)
            net_id = new_subnet['network_id']
            # update df controller with subnet
            self.nb_api.update_subnet(
                new_subnet['id'],
                utils.ovn_name(net_id),
                enable_dhcp=new_subnet['enable_dhcp'],
                cidr=new_subnet['cidr'],
                dhcp_ip=new_subnet['allocation_pools'][0]['start'],
                gateway_ip=new_subnet['gateway_ip'],
                dns_nameservers=new_subnet.get('dns_nameservers', []))
            return new_subnet

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_subnet(self, context, id):
        orig_subnet = super(DFPlugin, self).get_subnet(context, id)
        net_id = orig_subnet['network_id']
        with context.session.begin(subtransactions=True):
            # delete subnet in DB
            super(DFPlugin, self).delete_subnet(context, id)
            # update df controller with subnet delete
            self.nb_api.delete_subnet(id, utils.ovn_name(net_id))

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_network(self, context, network):
        with context.session.begin(subtransactions=True):
            result = super(DFPlugin, self).create_network(context,
                                                          network)
            self._process_l3_create(context, result, network['network'])

        return self.create_network_nb_api(result)

    def create_network_nb_api(self, network):
        # Create a logical switch with a name equal to the Neutron network
        # UUID.  This provides an easy way to refer to the logical switch
        # without having to track what UUID OVN assigned to it.
        external_ids = {ovn_const.OVN_NETWORK_NAME_EXT_ID_KEY: network['name']}

        # TODO(DF): Undo logical switch creation on failure
        self.nb_api.create_lswitch(name=utils.ovn_name(network['id']),
                                   external_ids=external_ids,
                                   subnets=[])
        return network

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_network(self, context, network_id):
        with context.session.begin():
            super(DFPlugin, self).delete_network(context,
                                                 network_id)
        # TODO(gsagie) this patch is used to remove DHCP port
        # remove when we implement distributed DHCP service and dont use
        # q-dhcp
        for port in self.nb_api.get_all_logical_ports():
            if port.get_lswitch_id() == utils.ovn_name(network_id):
                self.nb_api.delete_lport(port.get_id())
        self.nb_api.delete_lswitch(utils.ovn_name(network_id))

    def _set_network_name(self, network_id, name):
        ext_id = [ovn_const.OVN_NETWORK_NAME_EXT_ID_KEY, name]
        self.nb_api.update_lswitch(utils.ovn_name(network_id),
                                   external_ids=ext_id)

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def update_network(self, context, network_id, network):
        pnet._raise_if_updates_provider_attributes(network['network'])
        # FIXME(arosen) - rollback...
        if 'name' in network['network']:
            self._set_network_name(id, network['network']['name'])
        with context.session.begin(subtransactions=True):
            return super(DFPlugin, self).update_network(context, network_id,
                                                        network)

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def update_port(self, context, id, port):
        with context.session.begin(subtransactions=True):
            parent_name, tag = self._get_data_from_binding_profile(
                context, port['port'])
            original_port = self._get_port(context, id)
            updated_port = super(DFPlugin, self).update_port(context, id,
                                                             port)

            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         updated_port)
            self.update_security_group_on_port(
                context, id, port, original_port, updated_port)

        external_ids = {
            ovn_const.OVN_PORT_NAME_EXT_ID_KEY: updated_port['name']}
        allowed_macs = self._get_allowed_mac_addresses_from_port(
            updated_port)

        chassis = None
        if 'binding:host_id' in updated_port:
            chassis = updated_port['binding:host_id']

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if updated_port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        self.nb_api.update_lport(name=updated_port['id'],
                                 macs=[updated_port['mac_address']],
                                 external_ids=external_ids,
                                 parent_name=parent_name, tag=tag,
                                 enabled=updated_port['admin_state_up'],
                                 port_security=allowed_macs,
                                 chassis=chassis,
                                 device_owner=updated_port.get('device_owner',
                                                               None))
        return updated_port

    def _get_data_from_binding_profile(self, context, port):
        if (ovn_const.OVN_PORT_BINDING_PROFILE not in port or
                not attr.is_attr_set(
                    port[ovn_const.OVN_PORT_BINDING_PROFILE])):
            return None, None
        parent_name = (
            port[ovn_const.OVN_PORT_BINDING_PROFILE].get('parent_name'))
        tag = port[ovn_const.OVN_PORT_BINDING_PROFILE].get('tag')
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
            # The tag range is defined by ovn-nb.ovsschema.
            # https://github.com/openvswitch/ovs/blob/ovn/ovn/ovn-nb.ovsschema
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

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def create_port(self, context, port):
        with context.session.begin(subtransactions=True):
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
            if (ovn_const.OVN_PORT_BINDING_PROFILE in port['port'] and
                    attr.is_attr_set(
                        port['port'][ovn_const.OVN_PORT_BINDING_PROFILE])):
                db_port[ovn_const.OVN_PORT_BINDING_PROFILE] = (
                    port['port'][ovn_const.OVN_PORT_BINDING_PROFILE])
            self._process_port_create_extra_dhcp_opts(context, db_port,
                                                      dhcp_opts)
        return self.create_port_in_nb_api(db_port, parent_name, tag)

    def create_port_in_nb_api(self, port, parent_name, tag):
        # The port name *must* be port['id'].  It must match the iface-id set
        # in the Interfaces table of the Open_vSwitch database, which nova sets
        # to be the port ID.
        external_ids = {ovn_const.OVN_PORT_NAME_EXT_ID_KEY: port['name']}
        allowed_macs = self._get_allowed_mac_addresses_from_port(port)
        ips = []
        if 'fixed_ips' in port:
            if 'ip_address' in port['fixed_ips'][0]:
                ips.append(port['fixed_ips'][0]['ip_address'])

        chassis = None
        if 'binding:host_id' in port:
            chassis = port['binding:host_id']

        tunnel_key = self._allocate_tunnel_key()

        # Router GW ports are not needed by dragonflow controller and
        # they currently cause error as they couldnt be mapped to
        # a valid ofport (or location)
        if port.get('device_owner') == const.DEVICE_OWNER_ROUTER_GW:
            chassis = None

        self.nb_api.create_lport(
            name=port['id'],
            lswitch_name=utils.ovn_name(port['network_id']),
            macs=[port['mac_address']], ips=ips,
            external_ids=external_ids,
            parent_name=parent_name, tag=tag,
            enabled=port.get('admin_state_up', None),
            chassis=chassis, tunnel_key=tunnel_key,
            port_security=allowed_macs,
            device_owner=port.get('device_owner', None))

        return port

    def _allocate_tunnel_key(self):
        # TODO(gsagie) need something that can reuse deleted keys
        self.global_id = self.global_id + 1
        return self.global_id

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_port(self, context, port_id, l3_port_check=True):
        self.nb_api.delete_lport(port_id)
        with context.session.begin():
            self.disassociate_floatingips(context, port_id)
            super(DFPlugin, self).delete_port(context, port_id)

    def extend_port_dict_binding(self, port_res, port_db):
        super(DFPlugin, self).extend_port_dict_binding(port_res, port_db)
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL

    def create_router(self, context, router):
        router = super(DFPlugin, self).create_router(
            context, router)
        router_name = utils.ovn_name(router['id'])
        external_ids = {ovn_const.OVN_ROUTER_NAME_EXT_ID_KEY:
                        router.get('name', 'no_router_name')}
        self.nb_api.create_lrouter(router_name, external_ids=external_ids,
                                   ports=[])

        # TODO(gsagie) rollback router creation on OVN failure
        return router

    def delete_router(self, context, router_id):
        router_name = utils.ovn_name(router_id)
        self.nb_api.delete_lrouter(router_name)
        ret_val = super(DFPlugin, self).delete_router(context,
                                                      router_id)
        return ret_val

    def add_router_interface(self, context, router_id, interface_info):
        add_by_port, add_by_sub = self._validate_interface_info(
            interface_info)
        if add_by_sub:
            subnet = self.get_subnet(context, interface_info['subnet_id'])
            port = {'port': {'network_id': subnet['network_id'], 'name': '',
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

        lrouter = utils.ovn_name(router_id)
        lswitch = utils.ovn_name(subnet['network_id'])
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))

        logical_port = self.nb_api.get_logical_port(port['id'])
        self.nb_api.add_lrouter_port(port['id'], lrouter, lswitch,
                                     mac=port['mac_address'],
                                     network=network,
                                     tunnel_key=logical_port.get_tunnel_key())
        interface_info['port_id'] = port['id']
        if 'subnet_id' in interface_info:
            del interface_info['subnet_id']
        return super(DFPlugin, self).add_router_interface(
            context, router_id, interface_info)

    def remove_router_interface(self, context, router_id, interface_info):
        new_router = super(DFPlugin, self).remove_router_interface(
            context, router_id, interface_info)

        subnet = self.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        self.nb_api.delete_lrouter_port(utils.ovn_name(router_id),
                                        utils.ovn_name(network_id))
        return new_router
