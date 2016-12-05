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

from neutron.plugins.common import constants as service_constants
from neutron.services.qos.notification_drivers import qos_base
from neutron_lib.plugins import directory

from dragonflow.db.neutron import lockedobjects_db as lock_db


class DFQosServiceNotificationDriver(
    qos_base.QosServiceNotificationDriverBase):
    """Dragonflow notification driver for QoS."""

    def __init__(self):
        self._nb_api = None

    def get_description(self):
        return "Notification driver for Dragonflow"

    @property
    def _plugin(self):
        return directory.get_plugin(service_constants.QOS)

    @property
    def nb_api(self):
        if self._nb_api is None:
            plugin = directory.get_plugin()
            mech_driver = plugin.mechanism_manager.mech_drivers['df'].obj
            self._nb_api = mech_driver.nb_api

        return self._nb_api

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_CREATE_OR_UPDATE)
    def create_policy(self, context, policy):
        self.nb_api.qos_policy.create(policy['id'],
                                      policy['tenant_id'],
                                      name=policy['name'],
                                      rules=policy.get('rules', []),
                                      version=policy['revision_number'])

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_CREATE_OR_UPDATE)
    def update_policy(self, context, policy):
        policy_id = policy['id']
        # NOTE: Neutron will not pass policy with latest revision_number
        # in argument. Get the latest policy from neutron.
        policy_neutron = self._plugin.get_policy(context, policy_id)

        self.nb_api.qos_policy.update(
            policy_id, policy_neutron['tenant_id'],
            name=policy['name'], rules=policy_neutron['rules'],
            version=policy_neutron['revision_number'])

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_DELETE)
    def delete_policy(self, context, policy):
        policy_id = policy['id']
        # Only id will be in policy in the argument. Get full policy from
        # neutron.
        policy_neutron = self._plugin.get_policy(context, policy_id)

        self.nb_api.qos_policy.delete(policy_id, policy_neutron['tenant_id'])
