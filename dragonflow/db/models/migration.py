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

from dragonflow.db import field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.models import mixins


MIGRATION_STATUS_DEST_PLUG = 'dest_plug'
MIGRATION_STATUS_SRC_UNPLUG = 'src_unplug'
MIGRATION_STATUS_REBOUND = 'rebound'
MIGRATION_STATUSES = (MIGRATION_STATUS_DEST_PLUG,
                      MIGRATION_STATUS_SRC_UNPLUG,
                      MIGRATION_STATUS_REBOUND)


@mf.register_model
@mf.construct_nb_db_model
class Migration(mf.ModelBase, mixins.BasicEvents):
    table_name = 'migration'
    dest_chassis = df_fields.ReferenceField(core.Chassis)
    lport = df_fields.ReferenceField(l2.LogicalPort)
    status = df_fields.EnumField(MIGRATION_STATUSES, required=True)
