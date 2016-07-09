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

import netaddr

from dragonflow._i18n import _LE, _LI
from dragonflow.controller.common import constants as controller_const
from dragonflow.controller.common import utils
from dragonflow.controller.df_base_app import DFlowApp
from dragonflow.db import api_nb
from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall
from ryu.lib.packet import arp
from ryu.lib.packet import packet
from ryu.ofproto import ether

LOG = log.getLogger(__name__)

ARP_DETECT_INTERVAL = 30


class AllowedAddressPairsActiveDetector(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(AllowedAddressPairsActiveDetector, self).__init__(*args,
                                                                **kwargs)
        self.allowed_address_pairs_refs_list = {}
        self.api.register_table_handler(controller_const.ARP_TABLE,
                                        self.packet_in_handler)
        self.use_active_detection_for_allowed_address_pairs = \
            cfg.CONF.df.use_active_detection_for_allowed_address_pairs

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is None:
            LOG.error(_LE("No support for non ARP protocol"))
            return

        if (((arp_pkt.opcode == arp.ARP_REQUEST) and
                (arp_pkt.src_ip == arp_pkt.dst_ip)) or
                (arp_pkt.opcode == arp.ARP_REPLY)):
            match = msg.match
            in_port = match.get('in_port', 0)
            self._update_active_port_in_db(
                arp_pkt.src_ip, arp_pkt.src_mac, in_port)

    def _get_ips_in_allowed_address_pairs(self, lport):
        ips = []
        allowed_address_pairs = lport.get_allowed_address_pairs()
        if allowed_address_pairs is not None:
            for pair in allowed_address_pairs:
                ip = pair["ip_address"]
                if (netaddr.IPNetwork(ip).version == 4) and (ip not in ips):
                    # IPv6 addresses are not supported yet
                    ips.append(ip)

        return ips

    def _get_match_arp_reply(self, in_port, network_id, ip):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(in_port)
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_spa(utils.ipv4_text_to_int(str(ip)))
        match.set_arp_tpa(0)
        match.set_arp_opcode(arp.ARP_REPLY)
        match.set_metadata(network_id)
        return match

    def _get_match_gratuitous_arp(self, in_port, network_id, ip):
        target_ip = utils.ipv4_text_to_int(str(ip))
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(in_port)
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_spa(target_ip)
        match.set_arp_tpa(target_ip)
        match.set_arp_opcode(arp.ARP_REQUEST)
        match.set_metadata(network_id)
        return match

    def _get_instructions_packet_in(self):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

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

        arp_reply_match = self._get_match_arp_reply(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            self.get_datapath(),
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=arp_reply_match)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            self.get_datapath(),
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=gratuitous_arp_match)

    def _uninstall_flows_for_target_ip(self, ip, lport):
        ofproto = self.get_datapath().ofproto

        arp_reply_match = self._get_match_arp_reply(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=controller_const.ARP_TABLE,
            match=arp_reply_match,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=controller_const.ARP_TABLE,
            match=gratuitous_arp_match,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

    def _update_active_port_in_db(self, ip, mac, ofport):
        lports = self.db_store.get_ports()
        found_lport = None
        for lport in lports:
            if ofport == lport.get_external_value('ofport'):
                found_lport = lport
                break
        if found_lport is None:
            return

        network_id = found_lport.get_lswitch_id()
        topic = found_lport.get_topic()
        active_port = api_nb.AllowedAddressPairsActivePort({
            'network_id': network_id,
            'ip': ip,
            'detected_mac': mac,
            'detected_lport_id': found_lport.get_id(),
            'topic': topic
        })
        key = network_id + ip
        old_active_port = self.db_store.get_active_port(key)
        if old_active_port != active_port:
            LOG.info(_LI("Detected new active node. ip=%(ip)s, "
                         "mac=%(mac)s, lport_id=%(lport_id)s")
                     % {'ip': ip, 'mac': mac,
                        'lport_id': active_port.get_detected_lport_id()})
            self.nb_api.update_active_port(
                id=key,
                topic=active_port.get_topic(),
                network_id=active_port.get_network_id(),
                ip=active_port.get_ip(),
                detected_mac=active_port.get_detected_mac(),
                detected_lport_id=active_port.get_detected_lport_id())

    def _remove_active_port_from_db_by_lport(self, network_id, ip, lport):
        key = network_id + ip
        old_active_port = self.db_store.get_active_port(key)
        if old_active_port and \
                (old_active_port.get_detected_lport_id() == lport.get_id()):
            self.nb_api.delete_active_port(key, lport.get_topic())

    def _add_target_ip(self, ip, lport):
        # install flows which send the arp reply or gratuitous arp to
        # controller
        self._install_flows_for_target_ip(ip, lport)
        # send arp request
        self._send_arp_request(ip, lport)

        network_id = lport.get_lswitch_id()
        key = (network_id, ip)
        ip_refs_list = self.allowed_address_pairs_refs_list.get(key)
        lport_id = lport.get_id()
        if ip_refs_list is not None:
            if lport_id not in ip_refs_list:
                # add this ip to refs list
                ip_refs_list.append(lport_id)
        else:
            # create a refs list of this ip
            self.allowed_address_pairs_refs_list[key] = [lport_id]

    def _remove_target_ip(self, ip, lport):
        network_id = lport.get_lswitch_id()
        key = (network_id, ip)
        ip_refs_list = self.allowed_address_pairs_refs_list.get(key)
        if ip_refs_list is not None:
            # remove this ip from the refs list
            lport_id = lport.get_id()
            if lport_id in ip_refs_list:
                ip_refs_list.remove(lport_id)
                if len(ip_refs_list) == 0:
                    del self.allowed_address_pairs_refs_list[key]

        # uninstall flows which send the arp reply or gratuitous arp to
        # controller
        self._uninstall_flows_for_target_ip(ip, lport)

        # Try to remove the active node detected from this lport and used
        # this ip from dragonflow DB
        self._remove_active_port_from_db_by_lport(lport.get_lswitch_id(), ip,
                                                  lport)

    def _get_detect_items(self):
        items = []

        for target_ip, refs in self.allowed_address_pairs_refs_list.items():
            for lport_id in refs:
                lport = self.db_store.get_port(lport_id)
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
        mac = self.vswitch_api.get_local_port_mac_in_use(lport.get_id())
        if mac is not None:
            self.send_arp_request(mac,
                                  '0.0.0.0',
                                  ip,
                                  lport.get_external_value('ofport'))

    def _periodic_send_arp_request(self):
        """Spawn a thread to periodically to detect active node among
        ports with allowed-address-pairs.
        """
        periodic = loopingcall.FixedIntervalLoopingCall(
            self._send_arp_request_callback)
        periodic.start(interval=ARP_DETECT_INTERVAL)

    def switch_features_handler(self, ev):
        if self.use_active_detection_for_allowed_address_pairs:
            self._periodic_send_arp_request()

    def add_local_port(self, lport):
        if not self.use_active_detection_for_allowed_address_pairs:
            LOG.info(_LI("The active detection of allowed address pairs"
                         " is not enabled."))
            return

        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        ips = self._get_ips_in_allowed_address_pairs(lport)
        for target_ip in ips:
            self._add_target_ip(target_ip, lport)

    def update_local_port(self, lport, original_lport):
        if not self.use_active_detection_for_allowed_address_pairs:
            LOG.info(_LI("The active detection of allowed address pairs"
                         " is not enabled."))
            return

        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        ips = self._get_ips_in_allowed_address_pairs(lport)
        original_ips = self._get_ips_in_allowed_address_pairs(original_lport)

        for target_ip in ips:
            if target_ip not in original_ips:
                self._add_target_ip(target_ip, lport)

        for target_ip in original_ips:
            if target_ip not in ips:
                self._remove_target_ip(target_ip, original_lport)

    def remove_local_port(self, lport):
        if not self.use_active_detection_for_allowed_address_pairs:
            LOG.info(_LI("The active detection of allowed address pairs"
                         " is not enabled."))
            return

        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        ips = self._get_ips_in_allowed_address_pairs(lport)
        if len(ips) == 0:
            return

        for target_ip in ips:
            self._remove_target_ip(target_ip, lport)
