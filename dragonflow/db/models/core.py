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
import time

from jsonmodels import fields

from dragonflow import conf
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import mixins


@mf.register_model
@mf.construct_nb_db_model
class Chassis(mf.ModelBase, mixins.BasicEvents):
    table_name = 'chassis'

    ip = df_fields.IpAddressField(required=True)
    external_host_ip = df_fields.IpAddressField()
    tunnel_types = df_fields.EnumListField(conf.CONF.df.tunnel_types,
                                           required=True)


@mf.register_model
@mf.construct_nb_db_model
class Publisher(mf.ModelBase, mixins.Name):
    table_name = 'publisher'
    uri = fields.StringField()
    last_activity_timestamp = fields.FloatField()

    def is_stale(self):
        timeout = conf.CONF.df.publisher_timeout
        return (time.time() - self.last_activity_timestamp) > timeout

    @classmethod
    def on_get_all_post(self, instances):
        return [o for o in instances if not o.is_stale()]


@mf.register_model
@mf.construct_nb_db_model
class Listener(mf.ModelBase):
    table_name = "listener"

    timestamp = df_fields.TimestampField()
    ppid = fields.IntField()

    @property
    def topic(self):
        return 'listener_{id}'.format(id=self.id)

    def update_timestamp(self):
        self.timestamp = time.time()

    def on_create_pre(self):
        super(Listener, self).on_create_pre()
        self.update_timestamp()

    def on_update_pre(self):
        super(Listener, self).on_update_pre()
        self.update_timestamp()
