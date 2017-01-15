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
from jsonmodels import fields

from dragonflow.db import api_nb
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.utils import namespace


@mf.construct_nb_db_model(
    indexes=namespace.Namespace(
        id='id',
        id_topic=('id', 'topic'),
    ),
    events=('created', 'updated', 'deleted'),
)
class NbModelBase(mf.ModelBase):
    id = fields.StringField(required=True)
    topic = fields.StringField()


class VersionMixin(mf.MixinBase):
    version = fields.IntField()

    def is_newer_than(self, other):
        if other is None or self.version > other.version:
            return True
        else:
            return False


class NameMixin(mf.MixinBase):
    name = fields.StringField()


class UniqueKeyMixin(mf.MixinBase):
    unique_key = fields.IntField(required=True)

    def on_create_pre(self):
        nb_api = api_nb.NbApi.get_instance()
        self.unique_key = nb_api.driver.allocate_unique_key(self.table_name)
        super(UniqueKeyMixin, self).on_create()


@mf.register_model
@mf.construct_nb_db_model
class Chassis(NbModelBase, VersionMixin):
    table_name = 'chassis'

    ip = df_fields.IpAddressField(required=True)
    tunnel_types = df_fields.EnumListField(('vxlan', 'gre', 'geneve'),
                                           required=True)
