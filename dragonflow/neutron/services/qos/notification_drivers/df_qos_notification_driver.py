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

from oslo_log import log as logging

from neutron.common import exceptions as n_exc
from neutron import manager
from neutron.plugins.common import constants as service_constants
from neutron.services.qos.notification_drivers import qos_base

from dragonflow._i18n import _LE
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db.neutron import versionobjects_db as version_db

LOG = logging.getLogger(__name__)


class DFQosServiceNotificationDriver(
    qos_base.QosServiceNotificationDriverBase):
    """Dragonflow notification driver for QoS."""

    def __init__(self):
        self.nb_api = api_nb.NbApi.get_instance(True)

    def get_description(self):
        return "Notification driver for dragonflow"

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_CREATE_OR_UPDATE)
    def create_policy(self, context, policy):
        with context.session.begin(subtransactions=True):
            db_version = version_db._create_db_version_row(context.session,
                                                           policy['id'])

        self.nb_api.create_qos_policy(policy['id'],
                                      policy['tenant_id'],
                                      name=policy['name'],
                                      rules=policy.get('rules', []),
                                      version=db_version)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_CREATE_OR_UPDATE)
    def update_policy(self, context, policy):
        policy_id = policy['id']

        with context.session.begin(subtransactions=True):
            db_version = version_db._update_db_version_row(context.session,
                                                           policy_id)

        qos_plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.QOS)
        try:
            policy_neutron = qos_plugin.get_policy(context, policy_id)
        except n_exc.QosPolicyNotFound:
            LOG.exception(_LE('Could not get QoS policy %s'), policy_id)
            return

        self.nb_api.update_qos_policy(policy_id,
                                      policy['tenant_id'],
                                      name=policy['name'],
                                      rules=policy_neutron['rules'],
                                      version=db_version)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS_POLICY_DELETE)
    def delete_policy(self, context, policy):
        policy_id = policy['id']

        with context.session.begin(subtransactions=True):
            version_db._delete_db_version_row(context.session, policy_id)

        qos_plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.QOS)
        try:
            policy_neutron = qos_plugin.get_policy(context, policy_id)
        except n_exc.QosPolicyNotFound:
            LOG.exception(_LE('Could not get QoS policy %s'), policy_id)
            return

        self.nb_api.delete_qos_policy(policy_id, policy_neutron['tenant_id'])
