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


class Mapping(object):
    def __init__(self, bridge1, bridge2):
        self.bridge1 = bridge1
        self.bridge2 = bridge2
        key = [bridge1, bridge2]
        self.key = key.sort()

    def _extract_suffix(self, name):
        return name.split('-')[1] if '-' in name else name

    def gen_link_mapping(self,
                         bridge1_link_name=None,
                         bridge2_link_name=None):
        if bridge1_link_name is None:
            bridge1_link_name = "%s-%s-patch" % (
                self._extract_suffix(self.bridge2),
                self._extract_suffix(self.bridge1))
        if bridge2_link_name is None:
            bridge2_link_name = "%s-%s-patch" % (
                self._extract_suffix(self.bridge1),
                self._extract_suffix(self.bridge2))
        mapping = {self.bridge1: bridge1_link_name,
                   self.bridge2: bridge2_link_name}
        LOG.debug('genrated mappings {%(bridge1)s: %(link1)s,'
                  ' %(bridge2)s: %(link2)s}',
                  {'bridge1': self.bridge1,
                   'link1': bridge1_link_name,
                   'bridge2': self.bridge2,
                   'link2': bridge2_link_name})
        return mapping

    def __str__(self):
        return "%s-%s" % (self.key[0], self.key[1])
