# Copyright (c) 2015 OpenStack Foundation.
# All Rights Reserved.
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
from oslo.config import cfg
from oslo import messaging
from oslo.utils import importutils

from dragonflow.neutron.common.config import SDNCONTROLLER

from neutron import context as neutron_context
from neutron import manager

from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import l3_rpc
from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.common import constants as q_const
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import l3_hamode_db
from neutron.i18n import _LE, _LI, _LW
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

from neutron.db import common_db_mixin
from neutron.db import l3_gwmode_db
from neutron.db import l3_hascheduler_db

from oslo_log import log as logging

LOG = logging.getLogger(__name__)

NET_CONTROL_L3_OPTS = [
    cfg.StrOpt('L3controller_ip_list',
               default='tcp:172.16.10.10:6633',
               help=("L3 Controler IP list list tcp:ip_addr:port;"
                     "tcp:ip_addr:port..;..")),
    cfg.StrOpt('net_controller_l3_southbound_protocol',
               default='OpenFlow',
               help=("Southbound protocol to connect the forwarding"
                     "element Currently supports only OpenFlow"))
]

cfg.CONF.register_opts(NET_CONTROL_L3_OPTS)


def _notify_l3_agent_new_port(resource, event, trigger, **kwargs):
    LOG.debug('Received %s %s', resource, event)
    port = kwargs.get('port')
    if port is None:
        return

    l3plugin = manager.NeutronManager.get_service_plugins().get(
        constants.L3_ROUTER_NAT)
    mac_address_updated = kwargs.get('mac_address_updated')
    update_device_up = kwargs.get('update_device_up')
    context = kwargs.get('context')
    if context is None:
        LOG.warning(
            'Received %s %s without context [%s]',
            resource,
            event,
            port,
        )
        return
    if mac_address_updated or update_device_up:
        l3plugin.dvr_vmarp_table_update(context, port, "add")


def _notify_l3_agent_delete_port(event, resource, trigger, **kwargs):
    context = kwargs['context']
    port = kwargs['port']
    removed_routers = kwargs['removed_routers']
    l3plugin = manager.NeutronManager.get_service_plugins().get(
        constants.L3_ROUTER_NAT)
    l3plugin.dvr_vmarp_table_update(context, port, "del")
    if port['device_owner'] in q_const.ROUTER_INTERFACE_OWNERS:
        l3plugin.delete_router_interface(context, port)

    for router in removed_routers:
        l3plugin.remove_router_from_l3_agent(
            context, router['agent_id'], router['router_id'])


def subscribe():
    registry.subscribe(
        _notify_l3_agent_new_port, resources.PORT, events.AFTER_UPDATE)
    registry.subscribe(
        _notify_l3_agent_new_port, resources.PORT, events.AFTER_CREATE)
    registry.subscribe(
        _notify_l3_agent_delete_port, resources.PORT, events.AFTER_DELETE)


class ControllerL3ServicePlugin(common_db_mixin.CommonDbMixin,
                                l3_hamode_db.L3_HA_NAT_db_mixin,
                                l3_gwmode_db.L3_NAT_db_mixin,
                                l3_hascheduler_db.L3_HA_scheduler_db_mixin,
                                l3_rpc.L3RpcCallback):

    RPC_API_VERSION = '1.2'
    supported_extension_aliases = ["router", "ext-gw-mode",
        "l3_agent_scheduler"]

    def __init__(self):

        self.setup_rpc()
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver)
        #self.start_periodic_agent_status_check()
        self.ctx = neutron_context.get_admin_context()
        cfg.CONF.router_auto_schedule = True
        if cfg.CONF.net_controller_l3_southbound_protocol == "OpenFlow":
            # Open Flow Controller
            LOG.info(_LI("Using Southbound OpenFlow Protocol "))

            self.send_set_controllers_update(self.ctx, True)

            #self.controllerThread = ControllerRunner("openflow")
            #self.controllerThread.start()
            #self.controllerThread.router_scheduler = self.router_scheduler
            #self.controllerThread.endpoints = self.endpoints

        elif cfg.CONF.net_controller_l3_southbound_protocol == "OVSDB":
            LOG.error(_LE("Southbound OVSDB Protocol not implemented yet"))
        elif cfg.CONF.net_controller_l3_southbound_protocol == "OP-FLEX":
            LOG.error(_LE("Southbound OP-FLEX Protocol not implemented yet"))

        super(ControllerL3ServicePlugin, self).__init__()
        subscribe()

    def setup_rpc(self):
        # RPC support
        self.topic = topics.L3PLUGIN
        self.conn = n_rpc.create_connection(new=True)
        self.agent_notifiers.update(
            {q_const.AGENT_TYPE_L3: l3_rpc_agent_api.L3AgentNotifyAPI()})
        self.endpoints = [self]
        self.conn.create_consumer(self.topic, self.endpoints,
                                  fanout=True)
        self.conn.consume_in_threads()

    def get_plugin_type(self):
        return constants.L3_ROUTER_NAT

    def get_plugin_description(self):
        """Returns string description of the plugin."""
        return "L3 SDN Controller For Neutron"

    def dvr_vmarp_table_update(self, context, port_dict, action):
        """Notify the L3 agent of VM ARP table changes.

        Provide the details of the VM ARP to the L3 agent when
        a Nova instance gets created or deleted.
        """
        # Check this is a valid VM port
        if ("compute:" not in port_dict['device_owner'] or
            not port_dict['fixed_ips']):
            return
        subnet = port_dict['fixed_ips'][0]['subnet_id']
        filters = {'fixed_ips': {'subnet_id': [subnet]}}
        ports = self._core_plugin.get_ports(context, filters=filters)
        notify_port = None
        router_id = 0
        if action == "del":
            notify_port = port_dict

        for port in ports:
            # Check if this port subnet is connected to a router
            if port['device_owner'] in q_const.ROUTER_INTERFACE_OWNERS:
                router_id = port['device_id']
            if port['id'] == port_dict['id']:
                    notify_port = port
            if notify_port and router_id:
                break

        if notify_port:
            segmentation_id = self._get_segmentation_id(context, notify_port)
            self._send_new_port_notify(context, notify_port, action, router_id,
                    segmentation_id)
        else:
            LOG.error(_LE("Could not find port_id %(port_id)s"
                "in subnet %(subnet_id)s"),
                {"port_id": port_dict['id'],
                 "subnet_id": subnet})

    def _get_segmentation_id(self, context, port):
        port_data = self.get_ml2_port_bond_data(context, port['id'],
                        port['binding:host_id'])

        if port_data is None:
            return 0

        return port_data.get('segmentation_id', 0)

    def remove_router_from_l3_agent(self, context, agent_id, router_id):
        self.l3_rpc_notifier.router_deleted(context, router_id)

    def delete_router_interface(self, context, notify_port):
        self.l3_rpc_notifier.routers_updated(
            context,
            router_ids=[notify_port['device_id']],
            operation="del_interface",
            data={'port': notify_port},
        )

    def _send_new_port_notify(self, context, notify_port, action, router_id,
            segmentation_id):
        notify_port['segmentation_id'] = segmentation_id
        if action == "add":
            notify_action = self.l3_rpc_notifier.add_arp_entry
        elif action == "del":
            notify_action = self.l3_rpc_notifier.del_arp_entry
        notify_action(context, router_id, notify_port)
        self.send_set_controllers_update(context, False)
        return

    def get_ports_by_subnet(self, context, **kwargs):
        result = super(ControllerL3ServicePlugin, self).get_ports_by_subnet(
                                                                context,
                                                                **kwargs)
        if result:
            for port in result:
                port_data = self.get_ml2_port_bond_data(context, port['id'],
                                                      port['binding:host_id'])

                segmentation_id = 0
                if "segmentation_id" in port_data:
                    segmentation_id = port_data['segmentation_id']
                port['segmentation_id'] = segmentation_id
        return result

    def get_ml2_port_bond_data(self, ctx, port_id, device_id):
        core_plugin = manager.NeutronManager.get_plugin()
        port_context = core_plugin.get_bound_port_context(
            ctx, port_id, device_id)
        if not port_context:
            LOG.warning(_LW("Device %(device)s requested by agent "
                         "%(agent_id)s not found in database"),
                        {'device': device_id, 'agent_id': port_id})
            return None

        port = port_context.current

        try:
            segment = port_context.network.network_segments[0]
        except KeyError:
            if not segment:
                LOG.warning(_LW("Device %(device)s requested by agent "
                             " on network %(network_id)s not "
                             "bound, vif_type: "),
                            {'device': device_id,
                             'network_id': port['network_id']})
                return {}

        entry = {'device': device_id,
                 'network_id': port['network_id'],
                 'port_id': port_id,
                 'mac_address': port['mac_address'],
                 'admin_state_up': port['admin_state_up'],
                 'network_type': segment[api.NETWORK_TYPE],
                 'segmentation_id': segment[api.SEGMENTATION_ID],
                 'physical_network': segment[api.PHYSICAL_NETWORK],
                 'fixed_ips': port['fixed_ips'],
                 'device_owner': port['device_owner']}
        LOG.debug(("Returning: %s"), entry)
        return entry

    def auto_schedule_routers(self, context, host, router_ids):
        l3_agent = self.get_enabled_agent_on_host(
            context, q_const.AGENT_TYPE_L3, host)
        if not l3_agent:
            return False
        if self.router_scheduler:
            unscheduled_rs = self.router_scheduler._get_routers_to_schedule(
                                            context,
                                            self,
                                            router_ids)

            self.router_scheduler._bind_routers(context, self,
                    unscheduled_rs,
                    l3_agent)
        return

    def send_set_controllers_update(self, _context, force_reconnect):

        topic_port_update = topics.get_topic_name(topics.AGENT,
                                                  SDNCONTROLLER,
                                                  topics.UPDATE)
        target = messaging.Target(topic=topic_port_update)
        rpcapi = n_rpc.get_client(target)
        iplist = cfg.CONF.L3controller_ip_list

        rpcapi.cast(_context,
                    'set_controller_for_br',
                    br_id="br-int",
                    ip_address_list=iplist,
                    force_reconnect=force_reconnect,
                    protocols="OpenFlow13")
