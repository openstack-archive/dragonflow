# Copyright (c) 2016 OpenStack Foundation.
# All Rights Reserved.
#
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
from oslo_log import log

from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import qos


LOG = log.getLogger(__name__)


def _get_lport_qos_policy(lport):
    policy = lport.qos_policy
    if policy is None:
        policy = lport.lswitch.qos_policy

    return policy


class PortQosApp(df_base_app.DFlowApp):
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _add_local_port(self, lport):
        if not lport.is_vm_port():
            return

        policy = _get_lport_qos_policy(lport)
        self._update_lport_qos(lport, policy)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def _update_local_port(self, lport, original_lport):
        if not lport.is_vm_port():
            return

        policy = _get_lport_qos_policy(lport)
        old_policy = _get_lport_qos_policy(original_lport)
        if policy.id == old_policy.id:
            # Do nothing, if the port's qos is the same as db store.
            return

        self._update_lport_qos(lport, policy)

    def _update_lport_qos(self, lport, policy):
        if policy is None:
            # If the there is no qos associated with lport in nb db,
            # the qos in ovs db should also be checked and cleared.
            # This is because the ovs db might not be consistent with
            # nb db.
            self.vswitch_api.clear_port_qos(lport.id)
        else:
            self._update_local_port_qos(lport.id, policy)

    def _update_local_port_qos(self, port_id, policy):
        is_qos_set = policy.get_max_kbps() and policy.get_max_burst_kbps()
        old_qos = self.vswitch_api.get_port_qos(port_id)

        if old_qos is not None:
            if is_qos_set:
                if (
                    old_qos.id != policy.id or
                    policy.is_newer_than(old_qos)
                ):
                    # The QoS from north is not the same as ovs db.
                    self.vswitch_api.update_port_qos(port_id, policy)
            else:
                # The QoS from north is not set, clear the QoS in ovs db.
                self.vswitch_api.clear_port_qos(port_id)
        elif is_qos_set():
            self.vswitch_api.set_port_qos(port_id, policy)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        if not lport.is_vm_port():
            return

        # If removing lport in nb db, the qos in ovs db should also be checked
        # and cleared. This is because the ovs db might not be consistent with
        # nb db.
        self.vswitch_api.delete_port_qos_and_queue(lport.id)

    @df_base_app.register_event(qos.QosPolicy, model_constants.EVENT_UPDATED)
    def update_qos_policy(self, policy, orig_policy=None):
        for lport in self.db_store.get_all(
            l2.LogicalPort(qos_policy=policy.id),
            index=l2.LogicalPort.get_index('qos_policy_id'),
        ):
            self._update_local_port(lport.id, policy)

    @df_base_app.register_event(qos.QosPolicy, model_constants.EVENT_DELETED)
    def delete_qos_policy(self, policy):
        for lport in self.db_store.get_all(
            l2.LogicalPort(qos_policy=policy.id),
            index=l2.LogicalPort.get_index('qos_policy_id'),
        ):
            # FIXME (dimak) can this really happen?
            self.vswitch_api.clear_port_qos(lport.id)

    @df_base_app.register_event(l2.LogicalSwitch,
                                model_constants.EVENT_UPDATED)
    def _update_lswitch(self, lswitch, orig_lswitch):
        if lswitch.qos_policy.id == orig_lswitch.qos_policy.id:
            # QoS policy did not change, nothing to do here
            return

        new_policy = lswitch.qos_policy

        for lport in self.db_store.get_all(
            l2.LogicalPort(lswitch=lswitch.id),
            index=l2.LogicalPort.get_index('lswitch_id'),
        ):
            if lport.qos_policy is None:
                self._update_lport_qos(lport, new_policy)
