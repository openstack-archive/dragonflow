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

from dragonflow.controller.common import constants as const
from dragonflow.controller.common import cookies
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


AGING_COOKIE_NAME = 'aging'


class AgingApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(AgingApp, self).__init__(*args, **kwargs)
        self.do_aging = True
        self._aging_cookie = 0
        cookies.add_global_cookie_modifier(AGING_COOKIE_NAME, 1,
                                           lambda x: self._aging_cookie)

    """
    check_aging_needed()
        -> get_canary_flow()
            -> canary flow exist, get canary cookie
            -> no canary flow, i.e., first boot or ovs restart, no need to do
               aging
        -> renew_aging_cookie()
        -> add canary flows with new cookie
    after all apps flushed flows with new cookie, ovs_sync_finished() will
    be called
    """
    def ovs_sync_started(self):
        LOG.info("start aging")
        canary_flow = self._get_canary_flow()
        if not canary_flow:
            self.do_aging = False
            self._aging_cookie = 1
            LOG.info("no canary table, don't do aging")
        else:
            self.do_aging = True
            canary_cookie = canary_flow.cookie
            old_cookie = cookies.extract_value_from_cookie(AGING_COOKIE_NAME,
                                                           canary_cookie)
            self._aging_cookie = self._invert_cookie(old_cookie)
            LOG.info("renew cookie, old: %(old)x new: %(new)x",
                     {'old': canary_cookie, 'new': self._aging_cookie})
        # NOTE(oanson) cookie will be set automatically with _aging_cookie
        self.mod_flow(table_id=const.CANARY_TABLE)

    """
    now all apps had flushed flows with new cookie
    delete flows with old cookie
    """
    def ovs_sync_finished(self):
        if self.do_aging:
            # Give apps a few more seconds to finish their magic
            eventlet.spawn_after(5, self._start_aging)
            LOG.info("Scheduled aged flows deletion")

    def _invert_cookie(self, cookie):
        return 1 ^ cookie

    def _start_aging(self):
        inverted_cookie = self._invert_cookie(self._aging_cookie)
        old_cookie, old_mask = cookies.get_cookie(AGING_COOKIE_NAME,
                                                  inverted_cookie)
        self._cleanup_flows(old_cookie, old_mask)
        LOG.info("Scheduled aged flows deletion completed!")

    def _cleanup_flows(self, cookie, cookie_mask):
        self.mod_flow(cookie=cookie,
                      cookie_mask=cookie_mask,
                      table_id=self.ofproto.OFPTT_ALL,
                      match=self.parser.OFPMatch(),
                      command=self.ofproto.OFPFC_DELETE,
                      priority=0)

    def _get_canary_flow(self):
        canary_flow = self.get_flows(table_id=const.CANARY_TABLE)
        if not canary_flow:
            return None
        return canary_flow[0]
