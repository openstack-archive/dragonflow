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

import time

from oslo_config import cfg
from oslo_log import log
from ryu.controller import handler
from ryu.controller import ofp_event
from ryu.controller import ofp_handler
from ryu.ofproto import ofproto_v1_3
from ryu import utils

from dragonflow._i18n import _LE, _LI
from dragonflow.controller import dispatcher


LOG = log.getLogger(__name__)


class RyuDFAdapter(ofp_handler.OFPHandler):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    OF_AUTO_PORT_DESC_STATS_REQ_VER = 0x04

    def __init__(self, db_store=None, vswitch_api=None, nb_api=None):
        super(RyuDFAdapter, self).__init__(db_store=db_store,
                                           vswitch_api=vswitch_api,
                                           nb_api=nb_api)
        self.dispatcher = dispatcher.AppDispatcher('dragonflow.controller',
                                                   cfg.CONF.df.apps_list)
        self.db_store = db_store
        self.vswitch_api = vswitch_api
        self.nb_api = nb_api
        self._datapath = None
        self.table_handlers = {}

    @property
    def datapath(self):
        return self._datapath

    def start(self):
        super(RyuDFAdapter, self).start()
        self.load(self, db_store=self.db_store,
                  vswitch_api=self.vswitch_api,
                  nb_api=self.nb_api)
        self.wait_until_ready()

    def load(self, *args, **kwargs):
        self.dispatcher.load(*args, **kwargs)

    def is_ready(self):
        return self.datapath is not None

    def wait_until_ready(self):
        while not self.is_ready():
            time.sleep(3)

    def register_table_handler(self, table_id, handler):
        assert table_id not in self.table_handlers
        self.table_handlers[table_id] = handler

    def unregister_table_handler(self, table_id, handler):
        self.table_handlers.pop(table_id, None)

    def notify_update_logical_switch(self, lswitch=None):
        self.dispatcher.dispatch('update_logical_switch', lswitch=lswitch)

    def notify_remove_logical_switch(self, lswitch=None):
        self.dispatcher.dispatch('remove_logical_switch', lswitch=lswitch)

    def notify_add_local_port(self, lport=None):
        self.dispatcher.dispatch('add_local_port', lport=lport)

    def notify_update_local_port(self, lport=None, original_lport=None):
        self.dispatcher.dispatch('update_local_port', lport=lport,
                                 original_lport=original_lport)

    def notify_remove_local_port(self, lport=None):
        self.dispatcher.dispatch('remove_local_port', lport=lport)

    def notify_add_remote_port(self, lport=None):
        self.dispatcher.dispatch('add_remote_port', lport=lport)

    def notify_update_remote_port(self, lport=None, original_lport=None):
        self.dispatcher.dispatch('update_remote_port', lport=lport,
                                 original_lport=original_lport)

    def notify_remove_remote_port(self, lport=None):
        self.dispatcher.dispatch('remove_remote_port', lport=lport)

    def notify_update_bridge_port(self, lport=None):
        self.dispatcher.dispatch('update_bridge_port', lport=lport)

    def notify_add_router_port(self, router=None, router_port=None,
                               local_network_id=None):
        self.dispatcher.dispatch('add_router_port', router=router,
                                 router_port=router_port,
                                 local_network_id=local_network_id)

    def notify_remove_router_port(self,
                                  router_port=None, local_network_id=None):
        self.dispatcher.dispatch('remove_router_port',
                                 router_port=router_port,
                                 local_network_id=local_network_id)

    def notify_add_router_route(self, router=None, route=None):
        self.dispatcher.dispatch('add_router_route',
                                 router=router,
                                 route=route)

    def notify_remove_router_route(self, router=None, route=None):
        self.dispatcher.dispatch('remove_router_route',
                                 router=router,
                                 route=route)

    def notify_add_security_group_rule(self, secgroup, secgroup_rule):
        self.dispatcher.dispatch('add_security_group_rule',
                                 secgroup=secgroup,
                                 secgroup_rule=secgroup_rule)

    def notify_remove_security_group_rule(self, secgroup, secgroup_rule):
        self.dispatcher.dispatch('remove_security_group_rule',
                                 secgroup=secgroup,
                                 secgroup_rule=secgroup_rule)

    def notify_ovs_sync_finished(self):
        self.dispatcher.dispatch('ovs_sync_finished')

    def notify_ovs_sync_started(self):
        self.dispatcher.dispatch('ovs_sync_started')

    def notify_ovs_port_updated(self, ovs_port):
        self.dispatcher.dispatch('ovs_port_updated', ovs_port)

    def notify_ovs_port_deleted(self, ovs_port):
        self.dispatcher.dispatch('ovs_port_deleted', ovs_port)

    def notify_associate_floatingip(self, floatingip):
        self.dispatcher.dispatch('associate_floatingip', floatingip)

    def notify_disassociate_floatingip(self, floatingip):
        self.dispatcher.dispatch('disassociate_floatingip', floatingip)

    def notify_delete_floatingip(self, floatingip):
        self.dispatcher.dispatch('delete_floatingip', floatingip)

    @handler.set_ev_handler(ofp_event.EventOFPSwitchFeatures,
                            handler.CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        # TODO(oanson) is there a better way to get the datapath?
        self._datapath = ev.msg.datapath
        super(RyuDFAdapter, self).switch_features_handler(ev)
        version = self.datapath.ofproto.OFP_VERSION
        if version < RyuDFAdapter.OF_AUTO_PORT_DESC_STATS_REQ_VER:
            # Otherwise, this is done automatically by OFPHandler
            self._send_port_desc_stats_request(self.datapath)
        self.dispatcher.dispatch('switch_features_handler', ev)

    def _send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser
        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @handler.set_ev_handler(ofp_event.EventOFPPortDescStatsReply,
                            handler.MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        self.dispatcher.dispatch('port_desc_stats_reply_handler', ev)

    @handler.set_ev_handler(ofp_event.EventOFPPacketIn,
                            handler.MAIN_DISPATCHER)
    def OF_packet_in_handler(self, event):
        msg = event.msg
        table_id = msg.table_id
        if table_id in self.table_handlers:
            handler = self.table_handlers[table_id]
            handler(event)
        else:
            LOG.info(_LI("No handler for table id %s"), format(table_id))

    @handler.set_ev_handler(ofp_event.EventOFPErrorMsg,
                            handler.MAIN_DISPATCHER)
    def OF_error_msg_handler(self, event):
        msg = event.msg
        LOG.error(_LE('OFPErrorMsg received: type=0x%(type)02x '
                      'code=0x%(code)02x message=%(msg)s'),
                  {'type': msg.type, 'code': msg.code,
                   'msg': utils.hex_array(msg.data)})
