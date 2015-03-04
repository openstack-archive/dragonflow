# Copyright (c) 2014 OpenStack Foundation.
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

from neutron import context
from neutron import manager

from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import l3_rpc
from neutron.common import constants as q_const
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

from neutron.db import common_db_mixin
from neutron.db import l3_gwmode_db
from neutron.db import l3_dvrscheduler_db
from neutron.db import l3_hascheduler_db

from neutron.openstack.common import log as logging

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


class ControllerL3ServicePlugin(common_db_mixin.CommonDbMixin,
                                l3_gwmode_db.L3_NAT_db_mixin,
                                l3_hascheduler_db.L3_HA_scheduler_db_mixin,
                                l3_rpc.L3RpcCallback,
                                l3_dvrscheduler_db.L3_DVRsch_db_mixin):

    RPC_API_VERSION = '1.2'
    supported_extension_aliases = ["router", "ext-gw-mode", "dvr",
            "l3_agent_scheduler"]

    def __init__(self):

        self.setup_rpc()
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver)
        #self.start_periodic_agent_status_check()
        self.ctx = context.get_admin_context()
        cfg.CONF.router_auto_schedule = True
        if cfg.CONF.net_controller_l3_southbound_protocol == "OpenFlow":
            # Open Flow Controller
            LOG.info(("Using Southbound OpenFlow Protocol "))

            self.send_set_controllers_update(self.ctx, True)

            #self.controllerThread = ControllerRunner("openflow")
            #self.controllerThread.start()
            #self.controllerThread.router_scheduler = self.router_scheduler
            #self.controllerThread.endpoints = self.endpoints

        elif cfg.CONF.net_controller_l3_southbound_protocol == "OVSDB":
            LOG.error(("Southbound OVSDB Protocol not implemented yet"))
        elif cfg.CONF.net_controller_l3_southbound_protocol == "OP-FLEX":
            LOG.error(("Southbound OP-FLEX Protocol not implemented yet"))

        super(ControllerL3ServicePlugin, self).__init__()

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
        #ip_address = port_dict['fixed_ips'][0]['ip_address']
        subnet = port_dict['fixed_ips'][0]['subnet_id']
        filters = {'fixed_ips': {'subnet_id': [subnet]}}
        ports = self._core_plugin.get_ports(context, filters=filters)
        for port in ports:
            if (port['device_owner'] == q_const.DEVICE_OWNER_ROUTER_INTF or
                port['device_owner'] == q_const.DEVICE_OWNER_DVR_INTERFACE):
                router_id = port['device_id']
                #router_dict = self._get_router(context, router_id)
                port_data = self.get_ml2_port_bond_data(context, port['id'],
                        port['binding:host_id'])
                segmentation_id = 0
                if "segmentation_id" in port_data:
                    segmentation_id = port_data['segmentation_id']
                port['segmentation_id'] = segmentation_id
                if action == "add":
                    notify_action = self.l3_rpc_notifier.add_arp_entry
                elif action == "del":
                    notify_action = self.l3_rpc_notifier.del_arp_entry
                notify_action(context, router_id, port)
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
            LOG.warning(("Device %(device)s requested by agent "
                         "%(agent_id)s not found in database"),
                        {'device': device_id, 'agent_id': port_id})
            return {None}

        segment = port_context.bottom_bound_segment
        port = port_context.current

        if not segment:
            LOG.warning(("Device %(device)s requested by agent "
                         " on network %(network_id)s not "
                         "bound, vif_type: "),
                        {'device': device_id,
                         'network_id': port['network_id']})
            return {None}

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
            unscheduled_rs = self.router_scheduler.get_routers_to_schedule(
                                            context,
                                            self,
                                            router_ids)

            self.router_scheduler.bind_routers(context, self,
                    unscheduled_rs,
                    l3_agent)
        return

    def setup_vrouter_arp_responder(self, _context, br, action, table_id,
                                    segmentation_id, net_uuid, mac_address,
                                    ip_address):

        topic_port_update = topics.get_topic_name(topics.AGENT,
                                                  topics.PORT,
                                                  topics.UPDATE)
        target = messaging.Target(topic=topic_port_update)
        rpcapi = n_rpc.get_client(target)
        rpcapi.cast(_context,
                    'setup_entry_for_arp_reply_remote',
                    br_id="br-int",
                    action=action,
                    table_id=table_id,
                    segmentation_id=segmentation_id,
                    net_uuid=net_uuid,
                    mac_address=mac_address,
                    ip_address=ip_address)

    def update_agent_port_mapping_done(self, _context, agent_id, ip_address,
            host=None):
        LOG.debug(("::agent agent  <%s> on ip <%s> host <%s>  "),
                  agent_id,
                  ip_address,
                  host)
        self.send_set_controllers_update(_context, False)

    def send_set_controllers_update(self, _context, force_reconnect):

        topic_port_update = topics.get_topic_name(topics.AGENT,
                                                  topics.PORT,
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
