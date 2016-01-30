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

from dragonflow.controller.df_base_app import DFlowApp
from dragonflow.controller.ryu_base_app import RyuDFAdapter

AGING_COOKIE_MASK = 0x04


class Aging(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(Aging, self).__init__(*args, **kwargs)
        self.cookie_mask = AGING_COOKIE_MASK
        self.dispatcher = RyuDFAdapter.get_dispatcher()

    @staticmethod
    def _get_all_flows(datapath):
        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        cookie = cookie_mask = 0
        match = ofp_parser.OFPMatch(in_port=1)
        req = ofp_parser.OFPFlowStatsRequest(datapath, 0,
                                             ofp.OFPTT_ALL,
                                             ofp.OFPP_ANY, ofp.OFPG_ANY,
                                             cookie, cookie_mask,
                                             match)
        datapath.send_msg(req)

    def start_aging(self, datapath):
        self._get_all_flows(datapath)

    # when re-flush all flows done, one should call send_flow_stats_request
    def delete_stale_flows(self, ev):
        flows = []
        for stat in ev.msg.body:
            if (self.cookie & AGING_COOKIE_MASK) !=\
               (stat.cookie & AGING_COOKIE_MASK):
                # delete flow
                self.mod_flow(self.get_datapath(), cookie=stat.cookie,
                              cookie_mask=AGING_COOKIE_MASK,
                              command=self.get_datapath().ofproto.OFPFC_DELETE)

                flows.append('table_id=%s '
                             'duration_sec=%d duration_nsec=%d '
                             'priority=%d '
                             'idle_timeout=%d hard_timeout=%d flags=0x%04x '
                             'cookie=%d packet_count=%d byte_count=%d '
                             'match=%s instructions=%s' %
                             (stat.table_id,
                              stat.duration_sec, stat.duration_nsec,
                              stat.priority,
                              stat.idle_timeout, stat.hard_timeout, stat.flags,
                              stat.cookie, stat.packet_count, stat.byte_count,
                              stat.match, stat.instructions))
        self.logger.debug('delete stale flows: %s', flows)
