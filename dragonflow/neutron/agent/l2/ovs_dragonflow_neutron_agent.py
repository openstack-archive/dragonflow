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

from oslo_config import cfg

from neutron.agent.common import config
from neutron.agent.linux import ip_lib
from neutron.agent.ovsdb import api as ovsdb

from neutron.common import config as common_config
from neutron.common import utils as q_utils

from neutron.i18n import _, _LE, _LI
from neutron.plugins.common import constants as p_const

from neutron.plugins.openvswitch.agent import ovs_neutron_agent as ona
from neutron.plugins.openvswitch.common import constants

from oslo_log import log as logging

LOG = logging.getLogger(__name__)

agent_additional_opts = [
    cfg.StrOpt('L3controller_ip_list',
               default='tcp:localhost:6633',
               help=("L3 Controler IP list list tcp:ip_addr:port;"
                     "tcp:ip_addr:port..;..")),
    cfg.BoolOpt('enable_l3_controller', default=True,
                help=_("L3 SDN Controller"))
]

cfg.CONF.register_opts(agent_additional_opts, "AGENT")


class L2OVSControllerAgent(ona.OVSNeutronAgent):
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

        # Initialize controller
        self.controllers_ip_list = cfg.CONF.AGENT.L3controller_ip_list
        self.set_controller_for_br(self.int_br, self.controllers_ip_list)

    def set_controller_for_br(self, bridge, ip_address_list):
        '''Set OpenFlow Controller on the Bridge .
        :param bridge: the bridge object.
        :param ip_address_list: tcp:ip_address:port;tcp:ip_address2:port
        '''
        if not self.enable_l3_controller:
            LOG.info(_LI("Controller Base l3 is disabled on Agent"))
            return

        ip_address_ = ip_address_list.split(";")
        LOG.debug("Set Controllers on br %s to %s", bridge.br_name,
                  ip_address_)

        with self.set_controller_lock:
            bridge.del_controller()
            bridge.set_controller(ip_address_)
            self.set_connection_mode(bridge, "out-of-band")

            bridge.ovsdb.set_fail_mode(bridge.br_name,
                                       "standalone").execute(check_error=True)
            bridge.add_flow(priority=0, actions="normal")
            bridge.add_flow(table=constants.CANARY_TABLE,
                            priority=0,
                            actions="drop")

            # add the normal flow higher priority than the drop
            for br in self.phys_brs.values():
                br.add_flow(priority=3, actions="normal")

            # add the vlan flows
            cur_ports = self.int_br.get_vif_ports()
            # use to initialize once each local vlan
            l_vlan_map = set()
            for port in cur_ports:
                local_vlan_map = self.int_br.db_get_val("Port", port.port_name,
                                                        "other_config")
                local_vlan = self.int_br.db_get_val("Port", port.port_name,
                                                    "tag")
                net_uuid = local_vlan_map.get('net_uuid')
                if (net_uuid and local_vlan != ona.DEAD_VLAN_TAG and
                        net_uuid not in l_vlan_map):
                    l_vlan_map.add(net_uuid)
                    self.provision_local_vlan2(
                        local_vlan_map['net_uuid'],
                        local_vlan_map['network_type'],
                        local_vlan_map['physical_network'],
                        local_vlan_map['segmentation_id'])

    def check_ovs_status(self):
        if not self.enable_l3_controller:
            return super(L2OVSControllerAgent, self).check_ovs_status()

        # Check for the canary flow
        # Add lock to avoid race condition of flows
        with self.set_controller_lock:
            ret = super(L2OVSControllerAgent, self).check_ovs_status()
        return ret

    def _setup_tunnel_port(self, br, port_name, remote_ip, tunnel_type):
        ofport = super(L2OVSControllerAgent, self) \
                    ._setup_tunnel_port(
                    br,
                    port_name,
                    remote_ip,
                    tunnel_type)
        if ofport > 0:
            ofports = (ona._ofport_set_to_str
                       (self.tun_br_ofports[tunnel_type].values()))
            if self.enable_l3_controller:
                if ofports:
                    br.add_flow(table=constants.FLOOD_TO_TUN,
                                actions="move:NXM_NX_PKT_MARK[]"
                                        "->NXM_NX_TUN_ID[0..31],"
                                        "output:%s" %
                                        (ofports))
        return ofport

    def provision_local_vlan2(self, net_uuid, network_type, physical_network,
                             segmentation_id):
        if network_type == p_const.TYPE_VLAN:
            if physical_network in self.phys_brs:
                #outbound
                # The global vlan id is set in table 60
                # from segmentation id/tun id
                self.int_br.add_flow(table="60", priority=1,
                                     actions="move:NXM_NX_TUN_ID[0..11]"
                                     "->OXM_OF_VLAN_VID[],"
                                     "output:%s" %
                                     (self.int_ofports[physical_network]))
                lvid = self.local_vlan_map.get(net_uuid).vlan
                # inbound
                self.int_br.add_flow(priority=1000,
                                     in_port=self.
                                     int_ofports[physical_network],
                                     dl_vlan=segmentation_id,
                                     actions="mod_vlan_vid:%s,normal" % lvid)
            else:
                LOG.error(_LE("Cannot provision VLAN network for "
                              "net-id=%(net_uuid)s - no bridge for "
                              "physical_network %(physical_network)s"),
                          {'net_uuid': net_uuid,
                           'physical_network': physical_network})

    def set_connection_mode(self, bridge, mode):
        ovsdb_api = ovsdb.API.get(bridge)
        attrs = [('connection-mode', mode)]
        ovsdb_api.db_set('controller', bridge.br_name, *attrs).execute(
            check_error=True)


def main():
    cfg.CONF.register_opts(ip_lib.OPTS)
    config.register_root_helper(cfg.CONF)
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    q_utils.log_opt_values(LOG)

    try:
        agent_config = ona.create_agent_config_map(cfg.CONF)
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
