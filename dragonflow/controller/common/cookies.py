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

import collections

from oslo_log import log

from dragonflow._i18n import _LI, _LE
from dragonflow.common import exceptions


LOG = log.getLogger(__name__)


GLOBAL_APP_NAME = 'global cookie namespace'


"""Dictionary to hold a map from a task name to its cookie info"""
_cookies = {}
# Maximum number of bits that can be encoded. Taken from OVS
_cookie_max_bits = 64
# Maximum number of bits allocated to global cookies
_cookie_max_bits_global = 32
# Turn on all bits in the cookie mask. There are 64 (_cookie_max_bits)
# bits. -1 is all (infinite) bits on. Shift right and left again to have all
# bits but the least 64 bits on. Bitwise not to have only the 64 LSBits on.
_cookie_mask_all = ~((-1 >> _cookie_max_bits) << _cookie_max_bits)
# Maximum number of bits allocated to local cookies (total bits - global bits)
_cookie_max_bits_local = _cookie_max_bits - _cookie_max_bits_global
# Number of allocated bits for a given application (including global)
_cookies_used_bits = collections.defaultdict(int)


# A class holding the cookie's offset and bit-mask
CookieBitPair = collections.namedtuple('CookieBitPair', ('offset', 'mask'))


def register_cookie_bits(name, length, is_local=False, app_name=None):
    """Register this many cookie bits for the given 'task'. Local cookie space
    (as set by the is_local parameter) can be shared between applications
    (specified in app_name)
    :param name:     The name of the 'task'
    :type name:      string
    :param length:   The length of the cookie to allocate
    :type length:    int
    :param is_local: Is the cookie space local (i.e. shared)?
    :type is_local:  bool
    :param app_name: Owner application of the cookie (None for global)
    :type app_name:  string
    """
    if not is_local:
        app_name = GLOBAL_APP_NAME
        shift = 0
        max_bits = _cookie_max_bits_global
    else:
        shift = _cookie_max_bits_global
        max_bits = _cookie_max_bits_local
    if (app_name, name) in _cookies:
        LOG.info(_LI("Cookie for %(app_name)s/%(name)s already registered."),
                 {"app_name": app_name, "name": name})
        return
    if not app_name:
        raise TypeError(_LE("app_name must be provided if is_local is False"))
    start = _cookies_used_bits[app_name]
    if start + length > max_bits:
        LOG.error(_LE("Out of cookie space: "
                      "offset: %(offset)d length: %(length)d"),
                  {"offset": start, "length": length})
        raise exceptions.OutOfCookieSpaceException()
    _cookies_used_bits[app_name] = start + length
    start += shift
    mask = (_cookie_mask_all >> (_cookie_max_bits - length)) << start
    _cookies[(app_name, name)] = CookieBitPair(start, mask)
    LOG.info(_LI("Registered cookie for %(app_name)s/%(name)s, "
                 "mask: %(mask)x, offset: %(offset)d, length: %(length)d"),
             {"app_name": app_name, "name": name,
              "mask": mask, "offset": start, "length": length})


def get_cookie(name, value, old_cookie=0, old_mask=0,
               is_local=False, app_name=None):
    """Encode the given cookie value as the registered cookie. i.e. shift
    it to the correct location, and verify there are no overflows.
    :param name: The name of the 'task'
    :type name:        string
    :param value:      The value of the cookie to encode
    :type value:       int
    :param old_cookie: Encode this cookie alongside other cookie values
    :type old_cookie:  int
    :param old_mask:   The mask (i.e. encoded relevant bits) in old_cookie
    :type old_mask:  int
    :param is_local:   Is the cookie space local (i.e. shared)?
    :type is_local:    bool
    :param app_name:   Owner application of the cookie (None for global)
    :type app_name:    string
    """
    if not is_local:
        app_name = GLOBAL_APP_NAME
    if not app_name:
        raise TypeError(_LE("app_name must be provided if is_local is False"))
    pair = _cookies[(app_name, name)]
    mask_overlap = old_mask & pair.mask
    if mask_overlap != 0:
        if mask_overlap != pair.mask:
            raise exceptions.MaskOverlapException(app_name=app_name, name=name)
        return old_cookie, old_mask
    result_unmasked = (value << pair.offset)
    result = (result_unmasked & pair.mask)
    if result != result_unmasked:
        raise exceptions.CookieOverflowExcpetion(cookie=value,
                                      offset=pair.offset, mask=pair.mask)
    return result | (old_cookie & ~pair.mask), pair.mask | old_mask
