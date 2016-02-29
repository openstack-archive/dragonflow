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

import crc16

RedisClusterHashSlots = 16384


def key2slot(key):
    """
    Calculate keyslot for a given key.

    This also works for binary keys that is used in python 3.
    """
    k = unicode(key)
    start = k.find("{")

    if start > -1:
        end = k.find("}", start + 1)
        if end > -1 and end != start + 1:
            k = k[start + 1:end]

    return crc16.crc16xmodem(k) % RedisClusterHashSlots
