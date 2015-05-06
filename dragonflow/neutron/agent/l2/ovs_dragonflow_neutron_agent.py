# Copyright (c) 2015 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
import signal
import sys
import threading

import eventlet


eventlet.monkey_patch()

from dragonflow.neutron.common.config import SDNCONTROLLER

from oslo_config import cfg

from neutron.agent.common import config
from neutron.agent.linux import ip_lib
from neutron.agent.ovsdb import api as ovsdb
from neutron.agent import rpc as agent_rpc
from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.api.rpc.handlers import dvr_rpc

from neutron.common import config as common_config
from neutron.common import topics
from neutron.common import utils as q_utils
from neutron import context

from neutron.i18n import _, _LE, _LI
from neutron.plugins.openvswitch.agent import ovs_neutron_agent
from neutron.plugins.openvswitch.agent.ovs_neutron_agent import OVSNeutronAgent
from neutron.plugins.openvswitch.common import constants
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

agent_additional_opts = [
    cfg.BoolOpt('enable_l3_controller', default=True,
                help=_("L3 SDN Controller"))
]

cfg.CONF.register_opts(agent_additional_opts, "AGENT")


class L2OVSControllerAgent(OVSNeutronAgent):
    def __init__(self, integ_br, tun_br, local_ip,
                 bridge_mappings, polling_interval, tunnel_types=None,
                 veth_mtu=None, l2_population=False,
                 enable_distributed_routing=False,
                 minimize_polling=False,
                 ovsdb_monitor_respawn_interval=(
                         constants.DEFAULT_OVSDBMON_RESPAWN),
                 arp_responder=False,
                 prevent_arp_spoofing=False,
                 use_veth_interconnection=False,
                 quitting_rpc_timeout=None):

        if prevent_arp_spoofing:
            LOG.error(_LE("ARP Spoofing prevention is not"
                    " yet supported in Dragonflow feature disabled"))
            prevent_arp_spoofing = False

        # Initialize controller Ip List
        self.controllers_ip_list = None
        '''
        Sync lock for Race condition set_controller <--> check_ovs_status
        when setting the controller all the flow table are deleted
        by the time we set the CANARY_TABLE again.
        '''
        self.set_controller_lock = threading.Lock()
        self.enable_l3_controller = cfg.CONF.AGENT.enable_l3_controller

        super(L2OVSControllerAgent, self) \
            .__init__(integ_br,
                      tun_br, local_ip,
                      bridge_mappings,
                      polling_interval,
                      tunnel_types,
                      veth_mtu, l2_population,
                      enable_distributed_routing,
                      minimize_polling,
                      ovsdb_monitor_respawn_interval,
                      arp_responder,
                      prevent_arp_spoofing,
                      use_veth_interconnection,
                      quitting_rpc_timeout)

    def set_controller_for_br(self, context, br_id, ip_address_list,
                              force_reconnect=False, protocols="OpenFlow13"):
        '''Set OpenFlow Controller on the Bridge .
        :param br_id: the bridge id  .
        :param ip_address_list: tcp:ip_address:port;tcp:ip_address2:port
        :param force_reconnect: Force re setting the controller,remove i
        all flows
        '''
        if not self.enable_l3_controller:
            LOG.info(_LI("Controller Base l3 is disabled on Agent"))
            return
        bridge = None
        if (force_reconnect or not self.controllers_ip_list
            or self.controllers_ip_list != ip_address_list):
            self.controllers_ip_list = ip_address_list
            bridge = self.get_bridge_by_name(br_id)
            if not bridge:
                LOG.error(_LE("set_controller_for_br failur! no bridge  %s "),
                         br_id)
                return
            ip_address_ = ip_address_list.split(";")
            LOG.debug("Set Controllers on br %s to %s", br_id, ip_address_)
            self.set_controller_lock.acquire()
            bridge.del_controller()
            bridge.set_controller(ip_address_)
            if bridge.br_name == "br-int":
                bridge.add_flow(priority=0, actions="normal")
                bridge.add_flow(table=constants.CANARY_TABLE,
                                priority=0,
                                actions="drop")
                # Mark the tunnel ID so the data will be transferred to the
                # br-tun virtual switch, tun id and metadata are local
                bridge.add_flow(table="60", priority=1,
                                actions="move:NXM_NX_TUN_ID[0..31]"
                                        "->NXM_NX_PKT_MARK[],"
                                        "output:%s" %
                                        (self.patch_tun_ofport))
            # Set controller out-of-band mode in new way
            self.set_connection_mode(bridge, "out-of-band")
            self.set_controller_lock.release()

    def get_bridge_by_name(self, br_id):
        bridge = None
        if self.int_br.br_name == br_id:
            bridge = self.int_br
        elif self.tun_br.br_name == br_id:
            bridge = self.tun_br
        else:
            for physical_network in self.phys_brs:
                if self.phys_brs[physical_network].br_name == br_id:
                    bridge = self.phys_brs[physical_network]
                    break
        return bridge

    def check_ovs_status(self):
        if not self.enable_l3_controller:
            return super(L2OVSControllerAgent, self).check_ovs_status()

        # Check for the canary flow
        # Add lock to avoid race condition of flows
        self.set_controller_lock.acquire()
        ret = super(L2OVSControllerAgent, self).check_ovs_status()
        self.set_controller_lock.release()
        return ret

    def setup_rpc(self):
        self.agent_id = 'ovs-agent-%s' % cfg.CONF.host
        self.topic = topics.AGENT
        self.plugin_rpc = ovs_neutron_agent.OVSPluginApi(topics.PLUGIN)
        self.sg_plugin_rpc = sg_rpc.SecurityGroupServerRpcApi(topics.PLUGIN)
        self.dvr_plugin_rpc = dvr_rpc.DVRServerRpcApi(topics.PLUGIN)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)

        # RPC network init
        self.context = context.get_admin_context_without_session()
        # Handle updates from service
        self.endpoints = [self]
        # Define the listening consumers for the agent
        consumers = [[topics.PORT, topics.UPDATE],
                     [topics.PORT, topics.DELETE],
                     [topics.NETWORK, topics.DELETE],
                     [constants.TUNNEL, topics.UPDATE],
                     [constants.TUNNEL, topics.DELETE],
                     [topics.SECURITY_GROUP, topics.UPDATE],
                     [topics.DVR, topics.UPDATE]]
        if self.l2_pop:
            consumers.append([topics.L2POPULATION,
                              topics.UPDATE, cfg.CONF.host])
        if self.enable_l3_controller:
            consumers.append([SDNCONTROLLER,
                              topics.UPDATE])

        self.connection = agent_rpc.create_consumers(self.endpoints,
                                                     self.topic,
                                                     consumers,
                                                     start_listening=False)

    def _setup_tunnel_port(self, br, port_name, remote_ip, tunnel_type):
        ofport = super(L2OVSControllerAgent, self) \
                    ._setup_tunnel_port(
                    br,
                    port_name,
                    remote_ip,
                    tunnel_type)
        if ofport > 0:
            ofports = (ovs_neutron_agent._ofport_set_to_str
                           (self.tun_br_ofports[tunnel_type].values()))
            if self.enable_l3_controller:
                if ofports:
                    br.add_flow(table=constants.FLOOD_TO_TUN,
                                actions="move:NXM_NX_PKT_MARK[]"
                                        "->NXM_NX_TUN_ID[0..31],"
                                        "output:%s" %
                                        (ofports))
        return ofport

    def set_connection_mode(self, bridge, connection_mode):
        ovsdb_api = ovsdb.API.get(bridge)
        attrs = [('connection-mode', connection_mode)]
        ovsdb_api.db_set('controller', bridge.br_name, *attrs).execute(
            check_error=True)


def main():
    cfg.CONF.register_opts(ip_lib.OPTS)
    config.register_root_helper(cfg.CONF)
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    q_utils.log_opt_values(LOG)

    try:
        agent_config = ovs_neutron_agent.create_agent_config_map(cfg.CONF)
    except ValueError as e:
        LOG.error(_LE('%s Agent terminated!'), e)
        sys.exit(1)

    is_xen_compute_host = 'rootwrap-xen-dom0' in cfg.CONF.AGENT.root_helper
    if is_xen_compute_host:
        # Force ip_lib to always use the root helper to ensure that ip
        # commands target xen dom0 rather than domU.
        cfg.CONF.set_default('ip_lib_force_root', True)

    agent = L2OVSControllerAgent(**agent_config)

    signal.signal(signal.SIGTERM, agent._handle_sigterm)

    # Start everything.
    LOG.info(_LI("Agent initialized successfully, now running... "))
    agent.daemon_loop()


if __name__ == "__main__":
    main()
