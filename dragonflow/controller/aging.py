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
from dragonflow.controller.df_base_app import DFlowApp
from dragonflow.controller.ofswitch import OpenFlowSwitchMixin

LOG = log.getLogger("dragonflow.controller.aging")

aging_cookie = 0
global_cookie = 0


def get_global_cookie():
    return global_cookie


def flap_aging_cookie(cookie):
    c = cookie
    c |= (aging_cookie & const.GLOBAL_AGING_COOKIE_MASK)
    return c


def get_xor_aging_cookie(cookie):
    return cookie ^ 0x1


class Aging(DFlowApp, OpenFlowSwitchMixin):

    def __init__(self, *args, **kwargs):
        DFlowApp.__init__(self, *args, **kwargs)
        OpenFlowSwitchMixin.__init__(self, args[0])
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
        global aging_cookie
        canary_flow = self.get_canary_flow()
        if canary_flow is None:
            self.do_aging = False
            aging_cookie = const.GLOBAL_AGING_COOKIE_MASK
            LOG.info(_LI("no canary table, don't do aging"))
        else:
            self.renew_aging_cookie(canary_flow.cookie)
        self.add_canary_flow(aging_cookie)

    """
    now all apps had flushed flows with new cookie
    delete flows with old cookie
    """
    def ovs_sync_finished(self):
        if self.do_aging is True:
            self._start_aging()
            LOG.info(_LI("do aging"))

    def _start_aging(self):
        global aging_cookie
        old_cookie = get_xor_aging_cookie(aging_cookie)
        self.cleanup_flows(old_cookie, self.aging_mask)

    def renew_aging_cookie(self, cur_c):
        global aging_cookie
        LOG.info(_LI("renew cookie, current cookie is %x", cur_c))
        new_c = get_xor_aging_cookie(cur_c)
        aging_cookie = new_c & self.aging_mask
        return aging_cookie
