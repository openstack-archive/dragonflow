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

import eventlet
from oslo_log import log
from ryu.app.ofctl import api as ofctl_api
from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow._i18n import _
from dragonflow.controller.common import constants
from dragonflow.controller.common import cookies
from dragonflow.db import db_store


# TODO(heshan) This timeout constant should be configured in cfg file
DEFAULT_GET_FLOWS_TIMEOUT = 20
LOG = log.getLogger(__name__)


class DFlowApp(object):
    def __init__(self, api, vswitch_api=None, nb_api=None,
                 neutron_server_notifier=None):
        self.api = api
        self.db_store = db_store.get_instance()
        self.vswitch_api = vswitch_api
        self.nb_api = nb_api
        self.neutron_server_notifier = neutron_server_notifier
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

    def get_flows(self, datapath=None, table_id=None, timeout=None):
        if datapath is None:
            datapath = self.datapath
        if table_id is None:
            table_id = datapath.ofproto.OFPTT_ALL
        if not timeout:
            timeout = DEFAULT_GET_FLOWS_TIMEOUT
        parser = datapath.ofproto_parser
        msg = parser.OFPFlowStatsRequest(datapath, table_id=table_id)
        try:
            with eventlet.timeout.Timeout(seconds=timeout):
                replies = ofctl_api.send_msg(
                    self.api,
                    msg,
                    reply_cls=parser.OFPFlowStatsReply,
                    reply_multi=True)
        except BaseException:
            LOG.exception("Failed to get flows")
            return []
        if replies is None:
            LOG.error("No reply for get flows")
            return []
        flows = [body for reply in replies for body in reply.body]
        LOG.debug("Got the following flows: %s", flows)
        return flows

    def add_group(self, group_id, group_type, buckets, replace=False):
        """Add an entry to the groups table:

            :param group_id:    ID for the new group
            :param group_type:  Type of the new group, one of ofproto.OFPGT_*
            :param buckets:     List of parser.OFPBucket objects that define
                                group's actions.
        """
        if replace:
            self.del_group(
                group_id=group_id,
                group_type=group_type,
            )

        self._mod_group(
            command=self.ofproto.OFPGC_ADD,
            group_id=group_id,
            group_type=group_type,
            buckets=buckets,
        )

    def del_group(self, group_id, group_type):
        """Delete an entry from the groups table

            :param group_id:    ID of the group to delete.
                                To delete all groups use ofproto.OFPG_ALL.
            :param group_type:  Type of the group to delete.
        """
        self._mod_group(
            command=self.ofproto.OFPGC_DELETE,
            group_id=group_id,
            group_type=group_type,
        )

    def _mod_group(self, command, group_id, group_type, buckets=None):
        """Convenince function that sends a group modification message"""
        self.datapath.send_msg(
            self.parser.OFPGroupMod(
                datapath=self.datapath,
                command=command,
                group_id=group_id,
                type_=group_type,
                buckets=buckets,
            )
        )

    def dispatch_packet(self, pkt, unique_key):
        self.reinject_packet(
            pkt,
            table_id=constants.INGRESS_DISPATCH_TABLE,
            actions=[
                self.parser.OFPActionSetField(reg7=unique_key),
            ]
        )

    def reinject_packet(self, pkt, table_id=None, actions=None):
        datapath = self.datapath
        ofproto = datapath.ofproto
        parser = self.parser

        actions = actions or []
        if table_id is not None:
            actions.append(parser.NXActionResubmitTable(table_id=table_id))

        datapath.send_msg(
            parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER,
                actions=actions,
                data=pkt,
            ),
        )

    def send_arp_request(self, src_mac, src_ip, dst_ip, port_key):
        arp_request_pkt = packet.Packet()
        arp_request_pkt.add_protocol(ethernet.ethernet(
                                     ethertype=ether.ETH_TYPE_ARP,
                                     src=src_mac))

        arp_request_pkt.add_protocol(arp.arp(
                                    src_mac=src_mac,
                                    src_ip=src_ip,
                                    dst_ip=dst_ip))

        self.dispatch_packet(arp_request_pkt, port_key)

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
            _('{0} is not an event of {1}').format(event, model))

    def decorator(func):
        if not hasattr(func, '_register_events'):
            func._register_events = []
        func._register_events.append((model, event))
        return func
    return decorator
