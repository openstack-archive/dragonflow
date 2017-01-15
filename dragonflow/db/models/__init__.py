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
from dragonflow.db.models import legacy_models

# Remove those once we're done
NbObject = legacy_models.NbObject
NbDbObject = legacy_models.NbDbObject
UniqueKeyMixin = legacy_models.UniqueKeyMixin
LogicalSwitch = legacy_models.LogicalSwitch
Subnet = legacy_models.Subnet
LogicalPort = legacy_models.LogicalPort
LogicalRouter = legacy_models.LogicalRouter
LogicalRouterPort = legacy_models.LogicalRouterPort
SecurityGroup = legacy_models.SecurityGroup
SecurityGroupRule = legacy_models.SecurityGroupRule
Floatingip = legacy_models.Floatingip
QosPolicy = legacy_models.QosPolicy
Publisher = legacy_models.Publisher
AllowedAddressPairsActivePort = legacy_models.AllowedAddressPairsActivePort
Listener = legacy_models.Listener
OvsPort = legacy_models.OvsPort

UNIQUE_KEY = legacy_models.UNIQUE_KEY

table_class_mapping = legacy_models.table_class_mapping
