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
from dragonflow.controller.common import constants as const
from dragonflow.controller.ofswitch import OpenFlowSwitchMixin

aging_cookie = 0
global_cookie = 0


def renew_global_cookie(cookie, mask):
    global global_cookie
    global_cookie |= (cookie & mask)


def get_global_cookie():
    return global_cookie


def flap_aging_cookie(cookie):
    c = cookie
    c |= (aging_cookie & const.GLOBAL_AGING_COOKIE_MASK)
    return c


class Aging(DFlowApp, OpenFlowSwitchMixin):

    def __init__(self, *args, **kwargs):
        DFlowApp.__init__(*args, **kwargs)
        OpenFlowSwitchMixin.__init__(self, args[0], args[0].datapath)
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
        global aging_cookie
        canary_flow = self.get_canary_flow()
        if canary_flow is None:
            self.do_aging = False
            aging_cookie = const.GLOBAL_AGING_COOKIE_MASK
        else:
            aging_cookie = canary_flow.cookie
        self.add_canary_flow(aging_cookie)

    """
    now all apps had flushed flows with new cookie
    delete flows with cookies different with aging_cookie
    """
    def ovs_sync_finished(self):
        if self.do_aging is True:
            self._start_aging()

    def _start_aging(self):
        self.cleanup_flows(aging_cookie, self.aging_mask)

    """
        it should be called like this:
        new_cookie = renew_aging_cookie()
        re-flush flows with new_cookie
        add_canary_flow(new_cookie)
        ovs_sync_finished() to delete flows with old cookie
    """
    def renew_aging_cookie(self):
        global aging_cookie
        cur_c = self.get_aging_cookie()
        new_c = cur_c ^ 0x1
        aging_cookie = new_c & self.aging_mask
        renew_global_cookie(aging_cookie, self.aging_mask)
        return aging_cookie
