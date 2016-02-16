# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ryu.lib import addrconv
import struct

from dragonflow.controller.common import constants as const

UINT32_MAX = 0xffffffff
_aging_cookie = 0


def ipv4_text_to_int(ip_text):
    if ip_text == 0:
        return ip_text
    assert isinstance(ip_text, str)
    return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]


def mask_ntob(mask, err_msg=None):
    try:
        return (UINT32_MAX << (32 - mask)) & UINT32_MAX
    except ValueError:
        msg = 'illegal netmask'
        if err_msg is not None:
            msg = '%s %s' % (err_msg, msg)
            raise ValueError(msg)


def set_aging_cookie(c):
    global _aging_cookie
    _aging_cookie = c


def get_aging_cookie():
    return _aging_cookie


def set_aging_cookie_bits(cookie):
    # clear aging bits before using
    c = cookie & (~const.GLOBAL_AGING_COOKIE_MASK)
    c |= (_aging_cookie & const.GLOBAL_AGING_COOKIE_MASK)
    return c


def get_xor_cookie(cookie):
    return cookie ^ const.GLOBAL_INIT_AGING_COOKIE
