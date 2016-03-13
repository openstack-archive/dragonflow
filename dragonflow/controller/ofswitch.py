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

from oslo_log import log
from neutron.openstack.common import excutils
import eventlet
import ryu.exception as ryu_exc
from dragonflow.controller.common import constants as const
import ryu.app.ofctl.api as ofctl_api


LOG = log.getLogger("dragonflow.controller.df_local_controller")


class OpenFlowSwitchMixin(object):
    """
    Mixin to provide a convenient way to use OpenFlow messages synchronously
    """

    def __init__(self, *args, **kwargs):
        super(OpenFlowSwitchMixin, self).__init__(*args, **kwargs)
        self._app = kwargs.pop('ryu_app')
        self._dp = kwargs.pop('datapath')

    def _send_msg(self, msg, reply_cls=None, reply_multi=False):
        timeout_sec = 10  # TODO should be configured in cfg file
        timeout = eventlet.timeout.Timeout(seconds=timeout_sec)
        try:
            result = ofctl_api.send_msg(self, msg, reply_cls, reply_multi)
        except ryu_exc.RyuException as e:
            m = _("ofctl request %(request)s error %(error)s") % {
                "request": msg,
                "error": e,
            }
            LOG.error(m)
            raise RuntimeError(m)
        except eventlet.timeout.Timeout as e:
            with excutils.save_and_reraise_exception() as ctx:
                if e is timeout:
                    ctx.reraise = False
                    m = _("ofctl request %(request)s timed out") % {
                        "request": msg,
                    }
                    LOG.error(m)
                    raise RuntimeError(m)
        finally:
            timeout.cancel()
        LOG.debug("ofctl request %(request)s result %(result)s",
                  {"request": msg, "result": result})
        return result

    def _get_dp(self):
        dp = self._dp
        return dp, dp.ofproto, dp.ofproto_parser

    def dump_flows(self, table_id=None):
        (dp, ofp, ofpp) = self._get_dp()
        if table_id is None:
            table_id = ofp.OFPTT_ALL
        msg = ofpp.OFPFlowStatsRequest(dp, table_id=table_id)
        replies = ofpp.OFPFlowStatsRequest(msg,
                                           reply_cls=ofpp.OFPFlowStatsReply,
                                           reply_multi=True)
        flows = []
        for rep in replies:
            flows += rep.body
        return flows

    def cleanup_flows(self, match_c, match_cmask):
        cookies = set([f.cookie for f in self.dump_flows()])
        for c in cookies:
            if c == match_c & match_cmask:
                continue
            LOG.warn(_("Deleting flow with cookie 0x%(cookie)x") % {
                "cookie": c})
            self.delete_flows(cookie=c, cookie_mask=match_cmask)

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
        msg = ofpp.OFFlowMod(dp,
                             command=cmd,
                             cookie=cookie,
                             cookie_mask=cookie_mask,
                             table_id=table_id,
                             match=match,
                             priority=priority,
                             out_group=ofp.OFPG_ANY,
                             out_port=ofp.OFPP_ANY)
        self._send_msg(msg)

    def get_aging_cookie(self):
        f = self.dump_flows(table_id=const.CANARY_TABLE)
        if f is not None:
            return f.cookie & const.GLOBAL_AGING_COOKIE_MASK

    def add_canary_flow(self, cookie):
        (dp, ofp, ofpp) = self._get_dp()
        msg = ofpp.OFFlowMod(dp,
                             command=ofp.OFPFC_ADD,
                             cookie=cookie,
                             cookie_mask=const.GLOBAL_AGING_COOKIE_MASK,
                             table_id=const.CANARY_TABLE)
        self._send_msg(msg)

    def get_canary_flow(self):
        return self.dump_flows(table_id=const.CANARY_TABLE)
