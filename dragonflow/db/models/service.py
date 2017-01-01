# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from jsonmodels import fields
import six
import time
import uuid

from dragonflow import conf as cfg
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import core


SERVICE_ID_NAMESPACE = uuid.UUID('cf6b6d03-8eb8-473a-8058-ff5a44fb2ba9')


def generate_service_id(chassis, binary):
    chassis_id = chassis
    if not isinstance(chassis, six.string_types):
        chassis_id = chassis.id
    return str(uuid.uuid5(SERVICE_ID_NAMESPACE, ''.join((chassis_id, binary))))


@mf.register_model
@mf.construct_nb_db_model
class Service(mf.ModelBase):
    table_name = 'service'

    chassis = df_fields.ReferenceField(core.Chassis, required=True)
    binary = fields.StringField(required=True)
    last_seen_up = df_fields.TimestampField()
    disabled = fields.BoolField()
    disabled_reason = fields.StringField()

    def on_create_pre(self):
        self.id = generate_service_id(self.chassis, self.binary)

    def refresh_last_seen(self):
        """Refresh the timestamp in the last_seen_up field to now"""
        self.last_seen_up = time.time()

    @property
    def alive(self):
        """
        Returns true if the service is alive, i.e. if the last time it
        'checked in' is less than the <timeout> ago.
        :return:    True if the service is alive
        """
        last_seen_up = self.last_seen_up
        report_time_diff = time.time() - last_seen_up
        return (report_time_diff <= cfg.CONF.df.service_down_time)

    @classmethod
    def _update_last_seen(cls, nb_api, service_id):
        """
        Read the service for the given binary on the given chassis from the
        given nb database. Refresh it's last_seen_up field, and save it back
        into the database.
        :param nb_api:  NB dataabse API
        :type nb_api:   api_nb.NbApi
        :param chassis: The chassis on which the service runs
        :type chassis:  string or core.Chassis
        :param binary:  The name of the service on the chassis
        :type binary:   String
        """
        instance = nb_api.get(cls(id=service_id))
        instance.refresh_last_seen()
        nb_api.update(instance, skip_send_event=True)

    @classmethod
    def update_last_seen(cls, nb_api, chassis, binary):
        """
        Read the service for the given binary on the given chassis from the
        given nb database. Refresh it's last_seen_up field, and save it back
        into the database.
        :param nb_api:  NB dataabse API
        :type nb_api:   api_nb.NbApi
        :param chassis: The chassis on which the service runs
        :type chassis:  string or core.Chassis
        :param binary:  The name of the service on the chassis
        :type binary:   String
        """
        service_id = generate_service_id(chassis, binary)
        cls._update_last_seen(nb_api, service_id)

    @classmethod
    def is_alive(cls, nb_api, chassis, binary):
        """
        Read the service for the given binary on the given chassis from the
        given nb database. Returns true if the service is alive (as defined
        by the alive property)
        :param nb_api:  NB dataabse API
        :type nb_api:   api_nb.NbApi
        :param chassis: The chassis on which the service runs
        :type chassis:  string or core.Chassis
        :param binary:  The name of the service on the chassis
        :type binary:   String
        :return:        True if the service is alive
        """
        service_id = generate_service_id(chassis, binary)
        instance = nb_api.get(cls(id=service_id))
        return instance.alive
