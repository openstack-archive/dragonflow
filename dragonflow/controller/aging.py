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
import ofswitch

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


class Aging(DFlowApp, ofswitch.OpenFlowSwitchMixin):

    def __init__(self, *args, **kwargs):
        super(Aging, self).__init__(*args, **kwargs)
        self.aging_mask = const.GLOBAL_AGING_COOKIE_MASK

    # aging entry point
    def ovs_sync_finished(self):
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
