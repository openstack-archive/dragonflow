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

from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow._i18n import _LE
from dragonflow.controller.common import constants
from dragonflow.controller.common import cookies
from dragonflow.db import db_store2


class DFlowApp(object):
    def __init__(self, api, db_store=None, vswitch_api=None, nb_api=None):
        self.api = api
        self.db_store = db_store
        self.db_store2 = db_store2.get_instance()
        self.vswitch_api = vswitch_api
        self.nb_api = nb_api
        # Though there is nothing to initialize in super class, call it
        # will make the multi-inheritence work.
        super(DFlowApp, self).__init__()
        self._register_events()

    def _register_events(self):
        '''Iterate all methods we decorated with @register_event and register
        them to the requested models.
        '''
        for attr_name in dir(self):
            try:
                attr = getattr(self, attr_name)
                # NOTE (dimak) list() is needed here because sometimes we have
                # attributes that are mocks (during tests), who will have the
                # _register_events attribute (and any other attribute too).
                # list(mock.Mock()) yields an empty list so this works out
                # with little effort.
                args = list(attr._register_events)
            except (AttributeError, TypeError):
                # * AttributeError is OK because we stumbled upon an attribute
                #   with no _register_events
                # * TypeError is fine too because we have an attribute that has
                #   _register_events but its not iterable (for instance we have
                #   a _register_events method on an object we hold).
                continue

            for model, event in args:
                model.register(event, attr)

    @property
    def datapath(self):
        return self.api.datapath

    @property
    def parser(self):
        return self.datapath.ofproto_parser

    @property
    def ofproto(self):
        return self.datapath.ofproto

    @property
    def local_ports(self):
        return self.datapath.local_ports

    def add_flow_go_to_table(self, table, priority, goto_table_id,
                             datapath=None, match=None):

        if datapath is None:
            datapath = self.datapath

        inst = [datapath.ofproto_parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(datapath, inst=inst, table_id=table,
                      priority=priority, match=match)

    def mod_flow(self, datapath=None, cookie=0, cookie_mask=0, table_id=0,
                 command=None, idle_timeout=0, hard_timeout=0,
                 priority=0xff, buffer_id=0xffffffff, match=None,
                 actions=None, inst_type=None, out_port=None,
                 out_group=None, flags=0, inst=None):

        if datapath is None:
            datapath = self.datapath

        if command is None:
            command = datapath.ofproto.OFPFC_ADD

        if inst is None:
            if inst_type is None:
                inst_type = datapath.ofproto.OFPIT_APPLY_ACTIONS

            inst = []
            if actions is not None:
                inst = [datapath.ofproto_parser.OFPInstructionActions(
                    inst_type, actions)]

        if out_port is None:
            out_port = datapath.ofproto.OFPP_ANY

        if out_group is None:
            out_group = datapath.ofproto.OFPG_ANY

        cookie, cookie_mask = cookies.apply_global_cookie_modifiers(
            cookie, cookie_mask, self)

        message = datapath.ofproto_parser.OFPFlowMod(datapath, cookie,
                                                     cookie_mask,
                                                     table_id, command,
                                                     idle_timeout,
                                                     hard_timeout,
                                                     priority,
                                                     buffer_id,
                                                     out_port,
                                                     out_group,
                                                     flags,
                                                     match,
                                                     inst)

        datapath.send_msg(message)

    def send_packet(self, port, pkt):
        datapath = self.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=pkt)
        datapath.send_msg(out)

    def dispatch_packet(self, pkt, unique_key):
        datapath = self.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionSetField(reg7=unique_key),
                   parser.NXActionResubmitTable(
                       table_id=constants.INGRESS_DISPATCH_TABLE)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=pkt)
        datapath.send_msg(out)

    def send_arp_request(self, src_mac, src_ip, dst_ip, port):
        arp_request_pkt = packet.Packet()
        arp_request_pkt.add_protocol(ethernet.ethernet(
                                     ethertype=ether.ETH_TYPE_ARP,
                                     src=src_mac))

        arp_request_pkt.add_protocol(arp.arp(
                                    src_mac=src_mac,
                                    src_ip=src_ip,
                                    dst_ip=dst_ip))

        self.send_packet(port, arp_request_pkt)

    def register_local_cookie_bits(self, name, length):
        cookies.register_cookie_bits(name, length,
                                     True, self.__class__.__name__)

    def get_local_cookie(self, name, value, old_cookie=0, old_mask=0):
        return cookies.get_cookie(name, value,
                                  old_cookie=old_cookie, old_mask=old_mask,
                                  is_local=True,
                                  app_name=self.__class__.__name__)


def register_event(model, event):
    '''The decorator marks the method to be registered to the specified event

    :param model: Model holding the event
    :type model: Class
    :param event: Event name that method well be registerd to
    :type event: String
    '''
    if event not in model.get_events():
        raise RuntimeError(
            _LE('{0} is not an event of {1}').format(event, model),
        )

    def decorator(func):
        if not hasattr(func, '_register_events'):
            func._register_events = []
        func._register_events.append((model, event))
        return func
    return decorator
