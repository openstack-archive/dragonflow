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
# import netaddr

from dragonflow.db import crud
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
# from dragonflow.db import model_proxy
from dragonflow.utils import namespace


@mf.construct_nb_db_model(
    indexes=namespace.Namespace(
        id='id',
        id_topic=('id', 'topic'),
    ),
    events=('created', 'updated', 'deleted'),
    nb_crud=crud.NbApiCRUD,
)
class NbModelBase(mf.ModelBase):
    id = fields.StringField(required=True)
    topic = fields.StringField()


@mf.construct_nb_db_model
class NbDbModelBase(NbModelBase):
    name = fields.StringField()
    version = fields.IntField()


class NbDbUniqueKeyMixin(mf.ModelBase):
    unique_key = fields.IntField(required=True)
