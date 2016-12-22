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

from oslo_config import cfg
from ryu.lib import addrconv
import struct

from dragonflow.common import exceptions
from dragonflow.controller.common import constants as const

UINT32_MAX = 0xffffffff
_aging_cookie = 0
ACTIVE_PORT_DETECTION_APP = \
    "active_port_detection_app.ActivePortDetectionApp"


def ipv4_text_to_int(ip_text):
    try:
        return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]
    except Exception:
        raise exceptions.InvalidIPAddressException(key=ip_text)


def ipv6_text_to_int(ip_text):
    if isinstance(ip_text, unicode):
        ip_text = ip_text.encode('ascii', 'ignore')
    try:
        return list(struct.unpack('!8H', addrconv.ipv6.text_to_bin(ip_text)))
    except Exception:
        raise exceptions.InvalidIPAddressException(key=ip_text)


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


def check_active_port_detection_app():
    apps_list = cfg.CONF.df.apps_list
    if ACTIVE_PORT_DETECTION_APP in apps_list:
        return True
    return False
