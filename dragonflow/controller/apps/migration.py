# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log

from dragonflow import conf as cfg
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import migration


LOG = log.getLogger(__name__)


class MigrationApp(df_base_app.DFlowApp):
    @df_base_app.register_event(migration.Migration,
                                model_constants.EVENT_UPDATED)
    @df_base_app.register_event(migration.Migration,
                                model_constants.EVENT_CREATED)
    def update_migration(self, migration_obj, orig_migration_obj=None):
        """
        This method processes the migration event sent from source node.
        There are three parts for event process, source node, destination
        node, other nodes which related to topic of migrating VM, according
        to the chassis ID in lport, and local chassis..
        """
        if migration_obj.status != migration.MIGRATION_STATUS_SRC_UNPLUG:
            return
        original_lport = migration_obj.lport.get_object()
        lport = self.nb_api.get(original_lport)

        dest_chassis = migration_obj.dest_chassis
        if not dest_chassis:
            return

        chassis_name = cfg.CONF.host
        if dest_chassis.id == chassis_name:
            # destination node
            lport.binding = l2.PortBinding(
                type=l2.BINDING_CHASSIS,
                chassis=chassis_name,
            )
            self.db_store.update(lport)

            LOG.info("dest process migration event port = %(port)s"
                     "original_port = %(original_port)s"
                     "chassis = %(chassis)s"
                     "self_chassis = %(self_chassis)s",
                     {'port': lport,
                      'original_port': original_lport,
                      'chassis': dest_chassis.id,
                      'self_chassis': chassis_name})
            if original_lport:
                original_lport.emit_unbind_remote()
            lport.emit_bind_local()
            return

        # Here It could be either source node or other nodes, so
        # get ofport from chassis.
        remote_chassis = dest_chassis.get_object()
        if not remote_chassis:
            # chassis has not been online yet.
            return
        old_chassis = lport.binding.chassis
        lport.binding.chassis = dest_chassis

        LOG.info("src process migration event port = %(port)s"
                 "original_port = %(original_port)s"
                 "chassis = %(chassis)s",
                 {'port': lport,
                  'original_port': original_lport,
                  'chassis': dest_chassis})

        # source node and other related nodes
        if original_lport and old_chassis.id != chassis_name:
            original_lport.emit_unbind_remote()

        lport.emit_bind_remote()
