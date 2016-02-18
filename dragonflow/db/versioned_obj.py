# Copyright (c) 2015 OpenStack Foundation
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

from dragonflow.common import exceptions as df_exceptions

from oslo_log import log


LOG = log.getLogger(__name__)


def compare_and_increment_version(oid, json_obj, version):
    if oid and json_obj and 'version' in json_obj:
        LOG.debug("Neutron Object to be compared: %s, "
                  "version is %s" % (json_obj, str(version)))
        result = _compare_version(json_obj, version)
        if result == 0:
            return _increment_version(json_obj)

    # The only reason that throws this exception is that
    # the object version stored in DF DB is higher or
    # lower than it in Neutron DB, which means that the
    # object in DF DB is out-of-sync.
    raise df_exceptions.DBKeyBadVersionException(id=oid)


def create_version(json_obj):
    if json_obj:
        json_obj['version'] = 0
    return json_obj


def _increment_version(json_obj):
    json_obj['version'] = int(json_obj['version']) + 1
    return json_obj


def _compare_version(json_obj, version):
    return cmp(int(json_obj['version']), int(version))
