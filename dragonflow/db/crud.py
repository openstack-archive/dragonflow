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
import eventlet
from neutron_lib import constants as const
from oslo_log import log
from oslo_serialization import jsonutils

from dragonflow._i18n import _LW, _LE
import dragonflow.common.exceptions as df_exceptions
from dragonflow.db import db_common

LOG = log.getLogger(__name__)


class NbApiCRUD(object):
    def __init__(self, model, db_driver, publisher):
        self.model = model
        self.driver = db_driver
        self.publisher = publisher
        self.table_name = model.table_name

    def _send_db_change_event(self, table, key, action, value, topic):
        if self.publisher is None:
            return

        if not self.enable_selective_topo_dist:
            topic = db_common.SEND_ALL_TOPIC
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        self.publisher.send_event(update)
        eventlet.sleep(0)

    def create(self, obj):
        serialized_obj = jsonutils.dumps(obj.to_struct())
        self.driver.create_key(self.table_name, obj.id,
                               serialized_obj, obj.topic)
        self._send_db_change_event(self.table_name, obj.id, 'create',
                                   serialized_obj, obj.topic)

    def update(self, obj):
        full_obj = self.get(obj)

        for key, _ in obj:
            attr = getattr(obj, key)
            if attr is not None and attr != const.ATTR_NOT_SPECIFIED:
                setattr(full_obj, key, attr)

        serialized_obj = jsonutils.dumps(full_obj.to_struct())
        self.driver.set_key(self.table_name, full_obj.id,
                            serialized_obj, full_obj.topic)
        self._send_db_change_event(self.table_name, full_obj.id, 'set',
                                   serialized_obj, full_obj.topic)

    def delete(self, obj):
        try:
            self.driver.delete_key(self.table_name, obj.id, obj.topic)
            self._send_db_change_event(self.table_name, obj.id, 'delete',
                                    obj.id. obj.topic)
        except df_exceptions.DBKeyNotFound:
            LOG.warning(
                _LW('Could not find object %(id)s to delete in %(table)s'),
                extra={'id': id, 'table': self.table_name})
            raise

    def get(self, lean_obj):
        try:
            serialized_obj = self.driver.get_key(
                self.table_name,
                lean_obj.id,
                lean_obj.topic,
            )
            return self.model.from_json(serialized_obj)
        except df_exceptions.DBKeyNotFound:
            LOG.exception(
                _LE('Could not get object %(id)s from table %(table)s'),
                extra={'id': id, 'table': self.table_name})
            return None

    def get_all(self, topic=None):
        return [
            self.model.from_json(e)
            for e in self.driver.get_all_entries(self.table_name, topic)
        ]
