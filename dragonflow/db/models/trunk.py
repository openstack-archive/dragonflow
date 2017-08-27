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

import uuid

from jsonmodels import fields
from neutron_lib import constants as n_const

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import l2
from dragonflow.db.models import mixins


SUPPORTED_SEGMENTATION_TYPES = (n_const.TYPE_VLAN, )
UUID_NAMESPACE = uuid.UUID('a11fee2a-d833-4e22-be31-f915b55f1f77')


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'lport_id': 'port.id',
        'parent_id': 'parent.id',
    }
)
class ChildPortSegmentation(mf.ModelBase, mixins.Topic, mixins.BasicEvents):
    table_name = 'child_port_segmentation'

    parent = df_fields.ReferenceField(l2.LogicalPort, required=True)
    port = df_fields.ReferenceField(l2.LogicalPort, required=True)
    segmentation_type = df_fields.EnumField(SUPPORTED_SEGMENTATION_TYPES,
                                            required=True)
    segmentation_id = fields.IntField(required=True)
