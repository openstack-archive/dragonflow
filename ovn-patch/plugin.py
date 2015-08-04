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
from neutron.api.v2 import attributes
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
from neutron.i18n import _LE, _LI

from networking_ovn.common import config
from networking_ovn.common import constants as ovn_const
from networking_ovn.common import utils
from networking_ovn import ovn_nb_sync
from networking_ovn.ovsdb import impl_idl_ovn


LOG = log.getLogger(__name__)


class OVNPlugin(db_base_plugin_v2.NeutronDbPluginV2,
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
        super(OVNPlugin, self).__init__()
        LOG.info(_("Starting OVNPlugin"))
        self.vif_type = portbindings.VIF_TYPE_OVS
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}

        self._ovn = impl_idl_ovn.OvsdbOvnIdl()

        # Call the synchronization task, this sync neutron DB to OVN-NB DB
        # only in inconsistent states
        self.synchronizer = (
            ovn_nb_sync.OvnNbSynchronizer(self,
                                          self._ovn,
                                          config.get_ovn_neutron_sync_mode()))
        self.base_binding_dict = {
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_OVS,
            portbindings.VIF_DETAILS: {
                # TODO(rkukura): Replace with new VIF security details
                portbindings.CAP_PORT_FILTER:
                'security-group' in self.supported_extension_aliases}}

        self.synchronizer.sync()
        self._setup_rpc()

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
    def create_network(self, context, network):
        with context.session.begin(subtransactions=True):
            result = super(OVNPlugin, self).create_network(context,
                                                           network)
            self._process_l3_create(context, result, network['network'])

        return self.create_network_in_ovn(result)

    def create_network_in_ovn(self, network):
        # Create a logical switch with a name equal to the Neutron network
        # UUID.  This provides an easy way to refer to the logical switch
        # without having to track what UUID OVN assigned to it.
        external_ids = {ovn_const.OVN_NETWORK_NAME_EXT_ID_KEY: network['name']}

        # TODO(arosen): Undo logical switch creation on failure
        self._ovn.create_lswitch(lswitch_name=utils.ovn_name(network['id']),
                                 external_ids=external_ids).execute(
                                     check_error=True)
        return network

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_network(self, context, network_id):
        with context.session.begin():
            super(OVNPlugin, self).delete_network(context,
                                                  network_id)
        self._ovn.delete_lswitch(
            utils.ovn_name(network_id)).execute(check_error=True)

    def _set_network_name(self, network_id, name):
        ext_id = [ovn_const.OVN_NETWORK_NAME_EXT_ID_KEY, name]
        self._ovn.set_lswitch_ext_id(
            utils.ovn_name(network_id),
            ext_id).execute(check_error=True)

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def update_network(self, context, network_id, network):
        pnet._raise_if_updates_provider_attributes(network['network'])
        # FIXME(arosen) - rollback...
        if 'name' in network['network']:
            self._set_network_name(id, network['network']['name'])
        with context.session.begin(subtransactions=True):
            return super(OVNPlugin, self).update_network(context, network_id,
                                                         network)

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def update_port(self, context, id, port):
        self._validate_binding_profile(context, port)
        with context.session.begin(subtransactions=True):
            original_port = self._get_port(context, id)
            updated_port = super(OVNPlugin, self).update_port(context, id,
                                                              port)

            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         updated_port)
            self.update_security_group_on_port(
                context, id, port, original_port, updated_port)

        external_ids = {
            ovn_const.OVN_PORT_NAME_EXT_ID_KEY: updated_port['name']}
        parent_name, tag = self._get_data_from_binding_profile(updated_port)
        allowed_macs = self._get_allowed_mac_addresses_from_port(
            updated_port)
        self._ovn.set_lport(lport_name=updated_port['id'],
                            macs=[updated_port['mac_address']],
                            external_ids=external_ids,
                            parent_name=parent_name, tag=tag,
                            enabled=updated_port['admin_state_up'],
                            port_security=allowed_macs).execute(
                                check_error=True)
        return updated_port

    def _validate_binding_profile(self, context, port):
        if ovn_const.OVN_PORT_BINDING_PROFILE not in port:
            return
        parent_name = (
            port[ovn_const.OVN_PORT_BINDING_PROFILE].get('parent_name'))
        tag = port[ovn_const.OVN_PORT_BINDING_PROFILE].get('tag')
        if not any((parent_name, tag)):
            # An empty profile is fine.
            return
        if not all((parent_name, tag)):
            # If one is set, they both must be set.
            msg = _('Invalid binding:profile. parent_name and tag are '
                    'both required.')
            raise n_exc.InvalidInput(error_message=msg)
        if not isinstance(parent_name, six.string_types):
            msg = _('Invalid binding:profile. parent_name "%s" must be '
                    'a string.') % parent_name
            raise n_exc.InvalidInput(error_message=msg)
        if not isinstance(tag, int) or tag < 0 or tag > 4095:
            # The tag range is defined by ovn-nb.ovsschema.
            # https://github.com/openvswitch/ovs/blob/ovn/ovn/ovn-nb.ovsschema
            msg = _('Invalid binding:profile. tag "%s" must be '
                    'an int between 1 and 4096, inclusive.') % tag
            raise n_exc.InvalidInput(error_message=msg)
        # Make sure we can successfully look up the port indicated by
        # parent_name.  Just let it raise the right exception if there is a
        # problem.
        self.get_port(context, parent_name)

    def _get_data_from_binding_profile(self, port):
        parent_name = None
        tag = None
        if ovn_const.OVN_PORT_BINDING_PROFILE in port:
            # If binding:profile exists, we know the contents are valid as they
            # were validated in create_port_precommit().
            parent_name = (
                port[ovn_const.OVN_PORT_BINDING_PROFILE].get('parent_name'))
            tag = port[ovn_const.OVN_PORT_BINDING_PROFILE].get('tag')
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
            self._validate_binding_profile(context, port)
            dhcp_opts = port['port'].get(edo_ext.EXTRADHCPOPTS, [])
            db_port = super(OVNPlugin, self).create_port(context, port)
            sgids = self._get_security_groups_on_port(context, port)
            self._process_port_create_security_group(context, db_port,
                                                     sgids)
            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         db_port)

            db_port[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL
            self._process_port_create_extra_dhcp_opts(context, db_port,
                                                      dhcp_opts)
        return self.create_port_in_ovn(db_port)

    def create_port_in_ovn(self, port):
        # The port name *must* be port['id'].  It must match the iface-id set
        # in the Interfaces table of the Open_vSwitch database, which nova sets
        # to be the port ID.
        external_ids = {ovn_const.OVN_PORT_NAME_EXT_ID_KEY: port['name']}
        parent_name, tag = self._get_data_from_binding_profile(port)
        allowed_macs = self._get_allowed_mac_addresses_from_port(port)
        ips = []
        if 'fixed_ips' in port:
            if 'ip_address' in port['fixed_ips'][0]:
                ips.append(port['fixed_ips'][0]['ip_address'])
        self._ovn.create_lport(
            lport_name=port['id'],
            lswitch_name=utils.ovn_name(port['network_id']),
            macs=[port['mac_address']], ips=ips,
            external_ids=external_ids,
            parent_name=parent_name, tag=tag,
            enabled=port.get('admin_state_up', None),
            port_security=allowed_macs).execute(check_error=True)

        return port

    @oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                               retry_on_deadlock=True)
    def delete_port(self, context, port_id, l3_port_check=True):
        port = self.get_port(context, port_id)
        self._ovn.delete_lport(port_id,
                               utils.ovn_name(port['network_id'])
                               ).execute(check_error=True)
        with context.session.begin():
            self.disassociate_floatingips(context, port_id)
            super(OVNPlugin, self).delete_port(context, port_id)

    def extend_port_dict_binding(self, port_res, port_db):
        super(OVNPlugin, self).extend_port_dict_binding(port_res, port_db)
        port_res[portbindings.VNIC_TYPE] = portbindings.VNIC_NORMAL

    def create_router(self, context, router):
        router = super(OVNPlugin, self).create_router(
            context, router)
        router_name = utils.ovn_name(router['id'])
        external_ids = {ovn_const.OVN_ROUTER_NAME_EXT_ID_KEY:
                        router.get('name', 'no_router_name')}
        self._ovn.create_lrouter(router_name,
                                 external_ids=external_ids
                                 ).execute(check_error=True)

        # TODO(gsagie) rollback router creation on OVN failure
        return router

    def delete_router(self, context, router_id):
        router_name = utils.ovn_name(router_id)
        self._ovn.delete_lrouter(router_name).execute(check_error=True)
        ret_val = super(OVNPlugin, self).delete_router(context,
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
                             'mac_address': attributes.ATTR_NOT_SPECIFIED,
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

        self._ovn.add_lrouter_port(port['id'], lrouter, lswitch,
                                   mac=port['mac_address'],
                                   network=network).execute(check_error=True)
        interface_info['port_id'] = port['id']
        if 'subnet_id' in interface_info:
            del interface_info['subnet_id']
        return super(OVNPlugin, self).add_router_interface(
            context, router_id, interface_info)

    def remove_router_interface(self, context, router_id, interface_info):
        new_router = super(OVNPlugin, self).remove_router_interface(
            context, router_id, interface_info)

        subnet = self.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        self._ovn.delete_lrouter_port(utils.ovn_name(router_id),
                                      utils.ovn_name(network_id)
                                      ).execute(check_error=True)

