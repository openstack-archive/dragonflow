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

from neutron.agent.linux import utils as linux_utils
from oslo_log import log
from ryu.lib import addrconv
import struct

from dragonflow._i18n import _LE
from dragonflow.common import exceptions
from dragonflow.controller.common import constants as const

LOG = log.getLogger(__name__)

UINT32_MAX = 0xffffffff
_aging_cookie = 0


def ipv4_text_to_int(ip_text):
    try:
        return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]
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


def delete_conntrack_entries_by_filter(filter):
    cmd = ['conntrack', '-D']
    protocol = filter.get('protocol')
    if protocol:
        cmd.extend(['-p', str(protocol)])
    cmd.extend(['-f', filter.get('ethertype').lower()])
    nw_src = filter.get('nw_src')
    if nw_src:
        cmd.extend(['-s', nw_src])
    nw_dst = filter.get('nw_dst')
    if nw_dst:
        cmd.extend(['-d', nw_dst])
    zone = filter.get('zone_id')
    if zone:
        cmd.extend(['-w', str(zone)])

    try:
        linux_utils.execute(cmd, run_as_root=True, check_exit_code=True,
                            extra_ok_codes=[1])
        LOG.debug("Successfully executed conntrack command %s", cmd)
    except RuntimeError:
        LOG.exception(_LE("Failed execute conntrack command %s"), cmd)
