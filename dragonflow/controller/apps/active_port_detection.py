# Copyright (c) 2016 OpenStack Foundation.
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

import collections

from neutron_lib import constants as n_const
from oslo_log import log
from oslo_service import loopingcall
from ryu.lib.packet import arp
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow import conf as cfg
from dragonflow.controller.common import constants as controller_const
from dragonflow.controller import df_base_app
from dragonflow.db.models import active_port
from dragonflow.db.models import l2

LOG = log.getLogger(__name__)


class ActivePortDetectionApp(df_base_app.DFlowApp):

    """A application for detecting the active port for allowed address pairs

    When this application is loaded, gratuitous ARP / ARP reply packets using
    the address of a VM port's allowed address pairs will be monitored.  If
    any of those ARP packets arrives, a active port will be created with the
    sending VM port. The active port can be used by other applications (like
    L2App) to let packets to the address only be sent to the recorded VM port.
    When this application is not loaded, packets to a address in a allowed
    address pair will be broadcast to all VM ports with this allowed address
    pair.
    """

    def __init__(self, *args, **kwargs):
        super(ActivePortDetectionApp, self).__init__(*args, **kwargs)
        self.dection_interval_time = \
            cfg.CONF.df_active_port_detection.detection_interval_time
        self.allowed_address_pairs_refs_list = collections.defaultdict(set)
        self.api.register_table_handler(controller_const.ARP_TABLE,
                                        self.packet_in_handler)

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is None:
            LOG.error("No support for non ARP protocol")
            return

        if (arp_pkt.opcode == arp.ARP_REQUEST and
            arp_pkt.src_ip == arp_pkt.dst_ip) or \
                arp_pkt.opcode == arp.ARP_REPLY:
            match = msg.match
            unique_key = match.get('reg6')
            if not unique_key:
                return
            lport = self.db_store.get_one(
                        l2.LogicalPort(unique_key=unique_key),
                        index=l2.LogicalPort.get_index('unique_key'))
            if not lport:
                return
            self._update_active_port_in_db(
                arp_pkt.src_ip, arp_pkt.src_mac, lport)

    def _get_ips_in_allowed_address_pairs(self, lport):
        ips = set()
        allowed_address_pairs = lport.allowed_address_pairs
        for pair in allowed_address_pairs:
            ip = pair.ip_address
            if ip.version == n_const.IP_VERSION_4:
                ips.add(ip)
            else:
                # IPv6 addresses are not supported yet
                LOG.info("Don't support IPv6 addresses for now. IPv6"
                         " address %s will be ignored.", ip)

        return ips

    def _get_match_arp_reply(self, port_key, network_id, ip):
        match = self.parser.OFPMatch(reg6=port_key,
                                     eth_type=ether.ETH_TYPE_ARP,
                                     arp_spa=int(ip),
                                     arp_tpa=0,
                                     arp_op=arp.ARP_REPLY,
                                     metadata=network_id)
        return match

    def _get_match_gratuitous_arp(self, port_key, network_id, ip):
        target_ip = int(ip)
        match = self.parser.OFPMatch(reg6=port_key,
                                     eth_type=ether.ETH_TYPE_ARP,
                                     arp_spa=target_ip,
                                     arp_tpa=target_ip,
                                     arp_op=arp.ARP_REQUEST,
                                     metadata=network_id)
        return match

    def _get_instructions_packet_in(self):
        parser = self.parser
        ofproto = self.ofproto

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            controller_const.L2_LOOKUP_TABLE)
        inst = [action_inst, goto_inst]
        return inst

    def _install_flows_for_target_ip(self, ip, lport):
        instructions = self._get_instructions_packet_in()
        local_network_id = lport.lswitch.unique_key

        arp_reply_match = self._get_match_arp_reply(
            lport.unique_key,
            local_network_id,
            ip)
        self.mod_flow(
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=arp_reply_match)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.unique_key,
            local_network_id,
            ip)
        self.mod_flow(
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=gratuitous_arp_match)

    def _uninstall_flows_for_target_ip(self, ip, lport):
        ofproto = self.ofproto
        local_network_id = lport.lswitch.unique_key

        arp_reply_match = self._get_match_arp_reply(
            lport.unique_key,
            local_network_id,
            ip)
        self.mod_flow(
            table_id=controller_const.ARP_TABLE,
            match=arp_reply_match,
            command=ofproto.OFPFC_DELETE)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.unique_key,
            local_network_id,
            ip)
        self.mod_flow(
            table_id=controller_const.ARP_TABLE,
            match=gratuitous_arp_match,
            command=ofproto.OFPFC_DELETE)

    def _get_active_port_id(self, lswitch, ip_str):
        return lswitch.id + ip_str

    def _update_active_port_in_db(self, ip_str, mac, lport):
        lswitch = lport.lswitch
        topic = lport.topic
        found_lport_id = lport.id
        key = self._get_active_port_id(lswitch, ip_str)
        old_active_port = self.db_store.get_one(
                active_port.AllowedAddressPairsActivePort(id=key))
        new_active_port = active_port.AllowedAddressPairsActivePort(
            id=key,
            topic=topic,
            network=lswitch.id,
            ip=ip_str,
            detected_mac=mac,
            detected_lport=found_lport_id
        )
        if not old_active_port:
            LOG.info("Detected new active node. ip=%(ip_str)s, "
                     "mac=%(mac)s, lport_id=%(lport_id)s",
                     {'ip': ip_str, 'mac': mac, 'lport_id': found_lport_id})
            self.nb_api.create(new_active_port)
        elif old_active_port != new_active_port:
            LOG.info("Detected update in active node. ip=%(ip_str)s, "
                     "mac=%(mac)s, lport_id=%(lport_id)s",
                     {'ip': ip_str, 'mac': mac, 'lport_id': found_lport_id})
            self.nb_api.update(new_active_port)

    def _remove_active_port_from_db_by_lport(self, lswitch, ip_str, lport):
        key = self._get_active_port_id(lswitch, ip_str)
        old_active_port = self.db_store.get_one(
                active_port.AllowedAddressPairsActivePort(id=key))
        if (old_active_port and
                old_active_port.detected_lport.id == lport.id):
            self.nb_api.delete(old_active_port)

    def _add_target_ip(self, ip, lport):
        # install flows which send the arp reply or gratuitous arp to
        # controller
        self._install_flows_for_target_ip(ip, lport)
        # send arp request
        self._send_arp_request(ip, lport)

        lswitch = lport.lswitch
        key = (lswitch.id, ip)
        lport_id = lport.id
        self.allowed_address_pairs_refs_list[key].add(lport_id)

    def _remove_target_ip(self, ip, lport):
        lswitch = lport.lswitch
        key = (lswitch.id, ip)
        lport_id = lport.id
        ip_refs_list = self.allowed_address_pairs_refs_list[key]
        if lport_id in ip_refs_list:
            ip_refs_list.remove(lport_id)
            if len(ip_refs_list) == 0:
                del self.allowed_address_pairs_refs_list[key]

        # uninstall flows which send the arp reply or gratuitous arp to
        # controller
        self._uninstall_flows_for_target_ip(ip, lport)

        # Try to remove the active node detected from this lport and used
        # this ip from dragonflow DB
        self._remove_active_port_from_db_by_lport(lport.lswitch,
                                                  str(ip), lport)

    def _get_detect_items(self):
        items = []

        for target_ip, refs in self.allowed_address_pairs_refs_list.items():
            for lport_id in refs:
                lport = self.db_store.get_one(l2.LogicalPort(id=lport_id))
                if lport is not None:
                    items.append((target_ip, lport))

        return items

    def _send_arp_request_callback(self):
        items = self._get_detect_items()
        for item in items:
            network_id, ip = item[0]
            lport = item[1]
            # send arp request
            self._send_arp_request(ip, lport)

    def _send_arp_request(self, ip, lport):
        mac = self.vswitch_api.get_local_port_mac_in_use(lport.id)
        if mac is not None:
            self.send_arp_request(mac,
                                  '0.0.0.0',
                                  ip,
                                  lport.unique_key)
        else:
            LOG.warning("Couldn't find a valid mac to detect active "
                        "port in lport %s.", lport.id)

    def _periodic_send_arp_request(self):
        """Spawn a thread to periodically to detect active node among
        ports with allowed-address-pairs.
        """
        periodic = loopingcall.FixedIntervalLoopingCall(
            self._send_arp_request_callback)
        periodic.start(interval=self.dection_interval_time)

    def switch_features_handler(self, ev):
        self._periodic_send_arp_request()

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        ips = self._get_ips_in_allowed_address_pairs(lport)
        for target_ip in ips:
            self._add_target_ip(target_ip, lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def _update_local_port(self, lport, original_lport):
        ips_set = self._get_ips_in_allowed_address_pairs(lport)
        original_ips_set = self._get_ips_in_allowed_address_pairs(
            original_lport)

        for target_ip in ips_set - original_ips_set:
            self._add_target_ip(target_ip, lport)

        for target_ip in original_ips_set - ips_set:
            self._remove_target_ip(target_ip, original_lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        ips = self._get_ips_in_allowed_address_pairs(lport)
        if not ips:
            return

        for target_ip in ips:
            self._remove_target_ip(target_ip, lport)
