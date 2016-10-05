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

from dragonflow._i18n import _LI
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils as cookie
from dragonflow.controller import df_base_app
from dragonflow.controller import ofswitch

LOG = log.getLogger("dragonflow.controller.aging")


class Aging(df_base_app.DFlowApp, ofswitch.OpenFlowSwitchMixin):

    def __init__(self, *args, **kwargs):
        df_base_app.DFlowApp.__init__(self, *args, **kwargs)
        ofswitch.OpenFlowSwitchMixin.__init__(self, args[0])
        self.aging_mask = const.GLOBAL_AGING_COOKIE_MASK
        self.do_aging = True

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
        LOG.info(_LI("start aging"))
        canary_flow = self.get_canary_flow()
        if not canary_flow:
            self.do_aging = False
            cookie.set_aging_cookie(const.GLOBAL_INIT_AGING_COOKIE)
            LOG.info(_LI("no canary table, don't do aging"))
        else:
            self.do_aging = True
            self._renew_aging_cookie(canary_flow.cookie)
        self.add_canary_flow(cookie.get_aging_cookie())

    """
    now all apps had flushed flows with new cookie
    delete flows with old cookie
    """
    def ovs_sync_finished(self):
        if self.do_aging:
            self._start_aging()
            LOG.info(_LI("do aging"))

    def _start_aging(self):
        old_cookie = cookie.get_xor_cookie(cookie.get_aging_cookie())
        self.cleanup_flows(old_cookie, self.aging_mask)

    def _renew_aging_cookie(self, cur_c):
        LOG.info(_LI("renew cookie, current cookie is %x"), cur_c)
        new_c = cookie.get_xor_cookie(cur_c)
        cookie.set_aging_cookie(new_c & self.aging_mask)
        return cookie.get_aging_cookie()
