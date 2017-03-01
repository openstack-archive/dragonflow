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

from jsonmodels import errors
from jsonmodels import fields

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import mixins


RULE_TYPE_DSCP_MARKING = 'dscp_marking'
RULE_TYPE_BANDWIDTH_LIMIT = 'bandwidth_limit'
RULE_TYPES = (RULE_TYPE_DSCP_MARKING, RULE_TYPE_BANDWIDTH_LIMIT)


@mf.register_model
@mf.construct_nb_db_model
class QosPolicyRule(mf.ModelBase, mixins.BasicEvents):
    type = df_fields.EnumField((RULE_TYPES), required=True)
    dscp_mark = fields.IntField()
    max_kbps = fields.IntField()
    max_burst_kbps = fields.IntField()

    def validate(self):
        """dscp_mark is required if type is dscp_marking. max_kbps and
        max_burst_kbps are required if type is bandwidth_limit
        """
        if self.type == RULE_TYPE_DSCP_MARKING:
            if self.dscp_mark is None:
                errors.ValidationError("dscp_mark is required if "
                                       "type is dscp_marking")
        elif self.type == RULE_TYPE_BANDWIDTH_LIMIT:
            if self.max_burst_kbps is None:
                errors.ValidationError("max_burst_kbps is required if "
                                       "type is bandwidth_limit")


@mf.register_model
@mf.construct_nb_db_model
class QosPolicy(mf.ModelBase, mixins.Topic, mixins.Version, mixins.Name,
                mixins.BasicEvents):
    table_name = "qospolicy"

    rules = fields.ListField(QosPolicyRule)

    def get_max_burst_kbps(self):
        for rule in self.rules:
            if rule.type == 'bandwidth_limit':
                return rule.max_burst_kbps

    def get_max_kbps(self):
        for rule in self.rules:
            if rule.type == 'bandwidth_limit':
                return rule.max_kbps

    def get_dscp_marking(self):
        for rule in self.rules:
            if rule.type == 'dscp_marking':
                return rule.dscp_mark
