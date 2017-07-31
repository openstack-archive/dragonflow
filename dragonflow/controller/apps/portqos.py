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

import collections

from oslo_log import log

from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import qos


LOG = log.getLogger(__name__)


class PortQosApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(PortQosApp, self).__init__(*args, **kwargs)
        self._local_ports = collections.defaultdict(set)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        self._check_update_local_port_qos(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def _update_local_port(self, lport, original_lport):
        if (original_lport and
                lport.qos_policy == original_lport.qos_policy):
            # Do nothing, if the port's qos is the same as db store.
            return

        if original_lport.qos_policy:
            self._local_ports[original_lport.qos_policy.id].discard(lport.id)
        self._check_update_local_port_qos(lport)

    def _check_update_local_port_qos(self, lport):
        policy = lport.qos_policy
        if not policy:
            # If the there is no qos associated with lport in nb db,
            # the qos in ovs db should also be checked and cleared.
            # This is because the ovs db might not be consistent with
            # nb db.
            self.vswitch_api.clear_port_qos(lport.id)
            return

        self._local_ports[lport.qos_policy.id].add(lport.id)
        self._update_local_port_qos(lport.id, policy)

    def _update_local_port_qos(self, port_id, policy):

        def _is_qos_set():
            return policy.get_max_kbps() and policy.get_max_burst_kbps()

        old_qos = self.vswitch_api.get_port_qos(port_id)

        if old_qos is not None:
            if _is_qos_set():
                if (
                    old_qos.id != policy.id or
                    policy.is_newer_than(old_qos)
                ):
                    # The QoS from north is not the same as ovs db.
                    self.vswitch_api.update_port_qos(port_id, policy)
            else:
                # The QoS from north is not set, clear the QoS in ovs db.
                self.vswitch_api.clear_port_qos(port_id)
        else:
            if _is_qos_set():
                self.vswitch_api.set_port_qos(port_id, policy)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        if lport.qos_policy:
            self._local_ports[lport.qos_policy.id].discard(lport.id)
        # If removing lport in nb db, the qos in ovs db should also be checked
        # and cleared. This is because the ovs db might not be consistent with
        # nb db.
        self.vswitch_api.delete_port_qos_and_queue(lport.id)

    @df_base_app.register_event(qos.QosPolicy, model_constants.EVENT_UPDATED)
    def update_qos_policy(self, policy, orig_policy=None):
        for port_id in self._local_ports[policy.id]:
            self._update_local_port_qos(port_id, policy)

    @df_base_app.register_event(qos.QosPolicy, model_constants.EVENT_DELETED)
    def delete_qos_policy(self, policy):
        ports = self._local_ports.pop(policy.id, ())
        for port_id in ports:
            self.vswitch_api.clear_port_qos(port_id)
