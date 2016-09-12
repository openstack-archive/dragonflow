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
import ryu.app.ofctl.api as ofctl_api
from ryu.app.ofctl import service
from ryu.base import app_manager
import ryu.exception as ryu_exc

from dragonflow._i18n import _LE
from dragonflow.controller.common import constants as const

LOG = log.getLogger("dragonflow.controller.ofswitch")


class OpenFlowSwitchMixin(object):
    """
    Mixin to provide a convenient way to use OpenFlow messages synchronously
    """

    def __init__(self, ryu_app):
        app_mgr = app_manager.AppManager.get_instance()
        self.ofctl_app = app_mgr.instantiate(service.OfctlService)
        self.ofctl_app.start()
        self._app = ryu_app

    def _send_msg(self, msg, reply_cls=None, reply_multi=False):
        timeout_sec = 20  # TODO(heshan) should be configured in cfg file
        timeout = eventlet.timeout.Timeout(seconds=timeout_sec)
        result = None
        try:
            result = ofctl_api.send_msg(self._app, msg, reply_cls, reply_multi)
        except ryu_exc.RyuException as e:
            m = _LE("ofctl request %(request)s error %(error)s") % {
                    "request": msg,
                    "error": e,
            }
            LOG.error(_LE("exception occurred, %s"), m)
        except eventlet.timeout.Timeout as e:
            LOG.error(_LE("exception occurred, %s"), e)
        finally:
            timeout.cancel()
        LOG.debug("ofctl request %(request)s result %(result)s",
                  {"request": msg, "result": result})
        return result

    def _get_dp(self):
        dp = self._app.datapath
        return dp, dp.ofproto, dp.ofproto_parser

    def dump_flows(self, table_id=None):
        (dp, ofp, ofpp) = self._get_dp()
        if table_id is None:
            table_id = ofp.OFPTT_ALL
        msg = ofpp.OFPFlowStatsRequest(dp, table_id=table_id)
        replies = self._send_msg(msg,
                                 reply_cls=ofpp.OFPFlowStatsReply,
                                 reply_multi=True)
        if replies is None:
            LOG.error(_LE("_send_msg failed when dump_flows"))
            return []
        flows = []
        for rep in replies:
            flows += rep.body
        LOG.debug("flows is: %s", str(flows))
        return flows

    def cleanup_flows(self, match_c, match_cmask):
        try:
            self.delete_flows(cookie=match_c, cookie_mask=match_cmask)
        except Exception as e:
            LOG.error(_LE("exception occurred when cleanup_flows %s"), e)

    @staticmethod
    def _match(ofpp, match, **match_kwargs):
        if match is not None:
            return match
        return ofpp.OFPMatch(**match_kwargs)

    def delete_flows(
            self, table_id=None, strict=False, priority=0,
            cookie=0, cookie_mask=0, match=None, **match_kwargs):
        (dp, ofp, ofpp) = self._get_dp()
        if table_id is None:
            table_id = ofp.OFPTT_ALL
        match = self._match(ofpp, match, **match_kwargs)
        if strict:
            cmd = ofp.OFPFC_DELETE_STRICT
        else:
            cmd = ofp.OFPFC_DELETE
        msg = ofpp.OFPFlowMod(dp,
                              command=cmd,
                              cookie=cookie,
                              cookie_mask=cookie_mask,
                              table_id=table_id,
                              match=match,
                              priority=priority,
                              out_group=ofp.OFPG_ANY,
                              out_port=ofp.OFPP_ANY)
        self._send_msg(msg)

    def add_canary_flow(self, cookie):
        (dp, ofp, ofpp) = self._get_dp()
        msg = ofpp.OFPFlowMod(dp,
                              command=ofp.OFPFC_ADD,
                              cookie=cookie,
                              cookie_mask=const.GLOBAL_AGING_COOKIE_MASK,
                              table_id=const.CANARY_TABLE)
        self._send_msg(msg)

    def get_canary_flow(self):
        canary_flow = self.dump_flows(table_id=const.CANARY_TABLE)
        if len(canary_flow) == 0:
            return None
        return canary_flow[0]
