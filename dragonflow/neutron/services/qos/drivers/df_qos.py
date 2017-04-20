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
import threading

from neutron.common import constants
from neutron.plugins.common import constants as service_constants
from neutron.services.qos.drivers import base
from neutron.services.qos import qos_consts
from neutron_lib.api.definitions import portbindings
from neutron_lib.plugins import directory
from oslo_log import log

from dragonflow.db import api_nb
from dragonflow.db.models import qos
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.db.models import qos as n_qos

LOG = log.getLogger(__name__)

SUPPORTED_RULES = {
    qos_consts.RULE_TYPE_BANDWIDTH_LIMIT: {
        qos_consts.MAX_KBPS: {
            'type:range': [0, constants.DB_INTEGER_MAX_VALUE],
        },
        qos_consts.MAX_BURST: {
            'type:range': [0, constants.DB_INTEGER_MAX_VALUE],
        },
    },
    qos_consts.RULE_TYPE_DSCP_MARKING: {
        qos_consts.DSCP_MARK: {'type:values': constants.VALID_DSCP_MARKS},
    }
}
VIF_TYPES = [
    portbindings.VIF_TYPE_OVS,
    portbindings.VIF_TYPE_VHOST_USER,
]
VNIC_TYPES = [portbindings.VNIC_NORMAL],


class DfQosDriver(base.DriverBase):
    def __init__(self, *args, **kwargs):
        super(DfQosDriver, self).__init__(*args, **kwargs)
        self.nb_api = api_nb.NbApi.get_instance(True)

    @property
    def _plugin(self):
        return directory.get_plugin(service_constants.QOS)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS)
    def create_policy(self, context, policy):
        self.nb_api.create(n_qos.qos_policy_from_neutron_qos_policy(policy))

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS)
    def update_policy(self, context, policy):
        policy_id = policy['id']
        # NOTE: Neutron will not pass policy with latest revision_number
        # in argument. Get the latest policy from neutron.
        policy_neutron = self._plugin.get_policy(context, policy_id)

        self.nb_api.update(
            n_qos.qos_policy_from_neutron_qos_policy(policy_neutron))

    @lock_db.wrap_db_lock(lock_db.RESOURCE_QOS)
    def delete_policy(self, context, policy):
        policy_id = policy['id']
        self.nb_api.delete(qos.QosPolicy(id=policy_id))

    @classmethod
    def create(cls):
        return cls(
            name='df',
            requires_rpc_notifications=False,
            supported_rules=SUPPORTED_RULES,
            vif_types=VIF_TYPES,
            vnic_types=VNIC_TYPES,
        )


_driver = None
_init_lock = threading.Lock()


def register():
    global _driver
    with _init_lock:
        if _driver is None:
            _driver = DfQosDriver.create()
            LOG.error('DF QoS driver registered')
