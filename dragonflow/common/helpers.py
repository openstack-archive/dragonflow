# Copyright (c) 2017 OpenStack Foundation.
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


LOG = log.getLogger(__name__)


class _Mapping(object):
    def __init__(self, bridge1, bridge2):
        self._key = sorted([bridge1, bridge2])
        self._bridge1_id = 0
        if self._key[0] == bridge2:
            self._bridge1_id = 1

    def key(self):
        return "%s-%s" % (self._key[0], self._key[1])

    def _extract_suffix(self, name):
        return name.split('-')[1] if '-' in name else name

    def gen_link_mapping(self,
                         bridge1_link_name=None,
                         bridge2_link_name=None):
        if bridge1_link_name is None:
            bridge1_link_name = "%s-patch" % self._key[1 - self._bridge1_id]
        if bridge2_link_name is None:
            bridge2_link_name = "%s-patch" % self._key[self._bridge1_id]
        mapping = {self._key[self._bridge1_id]: bridge1_link_name,
                   self._key[1 - self._bridge1_id]: bridge2_link_name}
        return mapping

    def __repr__(self):
        return self.key()


class _BridgeMappings(object):
    def __init__(self):
        self._mappings = {}

    def get(self, bridge1, bridge2):
        mapping = _Mapping(bridge1, bridge2)
        return self.get(mapping)

    def add_mapping(self, bridge1, bridge2,
                    mapping_func,
                    bridge1_link_name=None,
                    bridge2_link_name=None):

        mapping = _Mapping(bridge1, bridge2)
        if not self._mappings.get(mapping.key()):
            mapping.gen_link_mapping(
                    bridge1_link_name,
                    bridge2_link_name)
            bridge1_mapping = mapping_func(
                    bridge1,
                    bridge1_link_name,
                    bridge2_link_name)
            bridge2_mapping = mapping_func(
                    bridge2,
                    bridge2_link_name,
                    bridge1_link_name)
            self._mappings[mapping.key()] = {
                    bridge1: bridge1_mapping,
                    bridge2: bridge2_mapping}
        return self._mappings[mapping.key()]


BRIDGE_MAPPINGS = _BridgeMappings()


def generate_mapping(bridge1, bridge2, mapping_func,
                     bridge1_link_name=None,
                     bridge2_link_name=None):
    global BRIDGE_MAPPINGS
    return BRIDGE_MAPPINGS.add_mapping(bridge1, bridge2,
                                       mapping_func,
                                       bridge1_link_name,
                                       bridge2_link_name)
