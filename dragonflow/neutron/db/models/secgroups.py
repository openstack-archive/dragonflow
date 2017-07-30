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

import copy

from neutron.extensions import securitygroup as sg
from neutron_lib import constants as n_const

from dragonflow.db.models import secgroups
from dragonflow.neutron.common import constants as df_const


def _get_protocol_number(ip_proto):

    if ip_proto in sg.sg_supported_protocols:
        return n_const.IP_PROTOCOL_MAP.get(ip_proto)

    return int(ip_proto)


def security_group_rule_from_neutron_obj(secrule):
    kwargs = copy.copy(secrule)
    kwargs.pop('tenant_id', None)
    kwargs.pop('updated_at', None)
    kwargs.pop('created_at', None)
    kwargs.pop('description', None)
    kwargs.pop('tags', None)
    topic = kwargs.pop('project_id', None)
    if topic is not None:
        kwargs['topic'] = topic

    version = kwargs.pop('revision_number', None)
    if version is not None:
        kwargs['version'] = version

    ip_proto = kwargs.pop('protocol', None)
    if ip_proto is not None:
        kwargs['protocol'] = _get_protocol_number(ip_proto)

    return secgroups.SecurityGroupRule(**kwargs)


def security_group_from_neutron_obj(secgroup):
    sg_name = secgroup.get('name', df_const.DF_SG_DEFAULT_NAME)
    rules = secgroup.get('security_group_rules', [])
    rules_mdls = [security_group_rule_from_neutron_obj(rule) for rule in rules]
    return secgroups.SecurityGroup(
        id=secgroup['id'],
        topic=secgroup['tenant_id'],
        name=sg_name,
        rules=rules_mdls,
        version=secgroup['revision_number'])
