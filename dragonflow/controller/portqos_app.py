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

from dragonflow._i18n import _LE
from dragonflow.controller import df_base_app


LOG = log.getLogger(__name__)


class PortQosApp(df_base_app.DFlowApp):

    def add_local_port(self, lport):
        self._update_local_port_qos(lport)

    def update_local_port(self, lport, original_lport):
        self._update_local_port_qos(lport)

    def _update_local_port_qos(self, lport):
        qos_id = lport.get_qos_policy_id()
        if not qos_id:
            # If the there is no qos associated with lport in nb db,
            # the qos in ovs db should also be checked and cleared.
            # This is because the ovs db might not be consistent with
            # nb db.
            self.vswitch_api.clear_port_qos(lport.get_id())
            return

        qos = self.db_store.get_qos(qos_id)
        if not qos:
            LOG.error(_LE("Unable to get QoS %(qos)s from db store when "
                          "adding/updating local port %(port)s"),
                      {'qos': qos_id, 'port': lport.get_id()})
            return

        self.vswitch_api.update_port_qos(lport.get_id(), qos)

    def remove_local_port(self, lport):
        # If removing lport in nb db, the qos in ovs db should also be checked
        # and cleared. This is because the ovs db might not be consistent with
        # nb db.
        self.vswitch_api.delete_port_qos_and_queue(lport.get_id())

    def update_qos(self, qos):
        local_ports = self.db_store.get_local_ports(qos.get_topic())
        for port in local_ports:
            if port.get_qos_policy_id() == qos.get_id():
                self.vswitch_api.update_port_qos(port.get_id(), qos)
