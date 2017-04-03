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

from dragonflow.db.models import qos


def qos_rule_from_neutron_qos_rule(rule):
    if isinstance(rule, dict):
        rule_dict = copy.copy(rule)
    else:
        rule_dict = rule.to_dict()
    rule_dict.pop('qos_policy_id', None)
    return qos.QosPolicyRule(**rule_dict)


def qos_policy_from_neutron_qos_policy(policy):
        policy_dict = {
            'id': policy['id'],
            'topic': policy['project_id'],
            'name': policy['name'],
            'version': policy['revision_number'],
        }
        rules = policy.get('rules')
        if rules:
            policy_dict['rules'] = [qos_rule_from_neutron_qos_rule(rule)
                                    for rule in rules]
        return qos.QosPolicy(**policy_dict)
