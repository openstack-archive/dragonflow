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

import struct

from neutron.agent.common import utils
from oslo_config import cfg
from oslo_log import log
from ryu.lib import addrconv

from dragonflow._i18n import _LE
from dragonflow.common import exceptions
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import cookies

LOG = log.getLogger(__name__)

_aging_cookie = 0
ACTIVE_PORT_DETECTION_APP = \
    "active_port_detection_app.ActivePortDetectionApp"


AGING_COOKIE_NAME = 'aging'
AGING_COOKIE_LEN = 1
cookies.register_cookie_bits(AGING_COOKIE_NAME, AGING_COOKIE_LEN)


def ipv4_text_to_int(ip_text):
    try:
        return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]
    except Exception:
        raise exceptions.InvalidIPAddressException(key=ip_text)


def ipv6_text_to_short(ip_text):
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


def set_aging_cookie_bits(old_cookie, old_cookie_mask):
    return cookies.get_cookie(AGING_COOKIE_NAME, _aging_cookie,
                              old_cookie, old_cookie_mask)


def get_xor_cookie(cookie):
    return cookie ^ const.GLOBAL_INIT_AGING_COOKIE


def check_active_port_detection_app():
    apps_list = cfg.CONF.df.apps_list
    if ACTIVE_PORT_DETECTION_APP in apps_list:
        return True
    return False


def delete_conntrack_entries_by_filter(ethertype='IPv4', protocol=None,
                                       nw_src=None, nw_dst=None, zone=None):
    cmd = ['conntrack', '-D']
    if protocol:
        cmd.extend(['-p', str(protocol)])
    cmd.extend(['-f', ethertype.lower()])
    if nw_src:
        cmd.extend(['-s', nw_src])
    if nw_dst:
        cmd.extend(['-d', nw_dst])
    if zone:
        cmd.extend(['-w', str(zone)])

    try:
        utils.execute(cmd, run_as_root=True, check_exit_code=True,
                      extra_ok_codes=[1])
        LOG.debug("Successfully executed conntrack command %s", cmd)
    except RuntimeError:
        LOG.exception(_LE("Failed execute conntrack command %s"), cmd)
