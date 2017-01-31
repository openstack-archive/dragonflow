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
import netaddr

from oslo_log import log
from oslo_service import loopingcall
from ryu.lib.packet import arp
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow._i18n import _LE, _LI, _LW
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as controller_const
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app

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
            LOG.error(_LE("No support for non ARP protocol"))
            return

        if (arp_pkt.opcode == arp.ARP_REQUEST and
            arp_pkt.src_ip == arp_pkt.dst_ip) or \
                arp_pkt.opcode == arp.ARP_REPLY:
            match = msg.match
            in_port = match.get('in_port', None)
            if in_port:
                self._update_active_port_in_db(
                    arp_pkt.src_ip, arp_pkt.src_mac, in_port)

    def _get_ips_in_allowed_address_pairs(self, lport):
        ips = set()
        allowed_address_pairs = lport.get_allowed_address_pairs()
        for pair in allowed_address_pairs:
            ip = pair["ip_address"]
            if netaddr.IPNetwork(ip).version == 4:
                ips.add(ip)
            else:
                # IPv6 addresses are not supported yet
                LOG.info(_LI("Don't support IPv6 addresses for now. IPv6"
                             " address %s will be ignored."), ip)

        return ips

    def _get_match_arp_reply(self, in_port, network_id, ip):
        match = self.parser.OFPMatch()
        match.set_in_port(in_port)
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_spa(utils.ipv4_text_to_int(str(ip)))
        match.set_arp_tpa(0)
        match.set_arp_opcode(arp.ARP_REPLY)
        match.set_metadata(network_id)
        return match

    def _get_match_gratuitous_arp(self, in_port, network_id, ip):
        target_ip = utils.ipv4_text_to_int(str(ip))
        match = self.parser.OFPMatch()
        match.set_in_port(in_port)
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_spa(target_ip)
        match.set_arp_tpa(target_ip)
        match.set_arp_opcode(arp.ARP_REQUEST)
        match.set_metadata(network_id)
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

        arp_reply_match = self._get_match_arp_reply(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=arp_reply_match)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            inst=instructions,
            table_id=controller_const.ARP_TABLE,
            priority=controller_const.PRIORITY_MEDIUM,
            match=gratuitous_arp_match)

    def _uninstall_flows_for_target_ip(self, ip, lport):
        ofproto = self.ofproto

        arp_reply_match = self._get_match_arp_reply(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            table_id=controller_const.ARP_TABLE,
            match=arp_reply_match,
            command=ofproto.OFPFC_DELETE)

        gratuitous_arp_match = self._get_match_gratuitous_arp(
            lport.get_external_value('ofport'),
            lport.get_external_value('local_network_id'),
            ip)
        self.mod_flow(
            table_id=controller_const.ARP_TABLE,
            match=gratuitous_arp_match,
            command=ofproto.OFPFC_DELETE)

    def _if_old_active_port_need_update(self, old_port, ip, mac, found_lport):
        if (old_port.get_network_id() == found_lport.get_lswitch_id() and
           old_port.get_ip() == ip and
           old_port.get_detected_mac() == mac and
           old_port.get_topic() == found_lport.get_topic() and
           old_port.get_detected_lport_id() == found_lport.get_id()):
            return False

        return True

    def _update_active_port_in_db(self, ip, mac, ofport):
        lports = self.db_store.get_ports()
        found_lport = None
        for lport in lports:
            if ofport == lport.get_external_value('ofport'):
                found_lport = lport
                break
        if found_lport is None:
            LOG.info(_LI("There is no logical port matched this "
                         "ofport(%s)."), ofport)
            return

        network_id = found_lport.get_lswitch_id()
        topic = found_lport.get_topic()
        found_lport_id = found_lport.get_id()
        key = network_id + ip
        old_active_port = self.db_store.get_active_port(key)
        if (not old_active_port or self._if_old_active_port_need_update(
                old_active_port, ip, mac, found_lport)):
            LOG.info(_LI("Detected new active node. ip=%(ip)s, "
                         "mac=%(mac)s, lport_id=%(lport_id)s"),
                     {'ip': ip, 'mac': mac, 'lport_id': found_lport_id})
            if old_active_port:
                self.nb_api.update_active_port(
                    id=key,
                    topic=topic,
                    detected_mac=mac,
                    detected_lport_id=found_lport_id)
            else:
                self.nb_api.create_active_port(
                    id=key,
                    topic=topic,
                    network_id=network_id,
                    ip=ip,
                    detected_mac=mac,
                    detected_lport_id=found_lport_id)

    def _remove_active_port_from_db_by_lport(self, network_id, ip, lport):
        key = network_id + ip
        old_active_port = self.db_store.get_active_port(key)
        if (old_active_port and
                old_active_port.get_detected_lport_id() == lport.get_id()):
            self.nb_api.delete_active_port(key, lport.get_topic())

    def _add_target_ip(self, ip, lport):
        # install flows which send the arp reply or gratuitous arp to
        # controller
        self._install_flows_for_target_ip(ip, lport)
        # send arp request
        self._send_arp_request(ip, lport)

        network_id = lport.get_lswitch_id()
        key = (network_id, ip)
        lport_id = lport.get_id()
        self.allowed_address_pairs_refs_list[key].add(lport_id)

    def _remove_target_ip(self, ip, lport):
        network_id = lport.get_lswitch_id()
        key = (network_id, ip)
        lport_id = lport.get_id()
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
        else:
            LOG.warning(_LW("Couldn't find a valid mac to detect active "
                            "port in lport %s."), lport.get_id())

    def _periodic_send_arp_request(self):
        """Spawn a thread to periodically to detect active node among
        ports with allowed-address-pairs.
        """
        periodic = loopingcall.FixedIntervalLoopingCall(
            self._send_arp_request_callback)
        periodic.start(interval=self.dection_interval_time)

    def switch_features_handler(self, ev):
        self._periodic_send_arp_request()

    def add_local_port(self, lport):
        ips = self._get_ips_in_allowed_address_pairs(lport)
        for target_ip in ips:
            self._add_target_ip(target_ip, lport)

    def update_local_port(self, lport, original_lport):
        ips_set = self._get_ips_in_allowed_address_pairs(lport)
        original_ips_set = self._get_ips_in_allowed_address_pairs(
            original_lport)

        for target_ip in ips_set - original_ips_set:
            self._add_target_ip(target_ip, lport)

        for target_ip in original_ips_set - ips_set:
            self._remove_target_ip(target_ip, original_lport)

    def remove_local_port(self, lport):
        ips = self._get_ips_in_allowed_address_pairs(lport)
        if not ips:
            return

        for target_ip in ips:
            self._remove_target_ip(target_ip, lport)
