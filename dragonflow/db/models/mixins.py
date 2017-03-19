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

import dragonflow.db.model_framework as mf
from dragonflow.db.models import constants


@mf.construct_nb_db_model(indexes={'topic': 'topic'})
class Topic(mf.MixinBase):
    topic = fields.StringField(required=True)


@mf.construct_nb_db_model(
    events={
        constants.EVENT_CREATED,
        constants.EVENT_UPDATED,
        constants.EVENT_DELETED,
    },
)
class BasicEvents(mf.MixinBase):
    pass


class Version(mf.MixinBase):
    version = fields.IntField()

    def is_newer_than(self, other):
        return other is None or self.version > other.version


class Name(mf.MixinBase):
    name = fields.StringField()


@mf.construct_nb_db_model(indexes={'unique_key': 'unique_key'})
class UniqueKey(mf.MixinBase):
    unique_key = fields.IntField(required=True)

    def on_create_pre(self):
        super(UniqueKey, self).on_create_pre()

        # TODO(dimak) This is here due to api_nb->models.core->models.mixins
        # import cycle. Maybe we can break it by taking publisher/subscriber
        # initialization out of api_nb
        # Relevant bp:
        # https://blueprints.launchpad.net/dragonflow/+spec/pub-sub-v2
        from dragonflow.db import api_nb
        nb_api = api_nb.NbApi.get_instance(True)
        self.unique_key = nb_api.driver.allocate_unique_key(self.table_name)
