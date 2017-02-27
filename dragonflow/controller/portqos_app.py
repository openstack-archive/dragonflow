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
        if not self._is_vm_port(lport):
            return

        port_qos_id = self._get_lport_qos_policy_id(lport)
        self._check_update_local_port_qos(lport.get_id(), port_qos_id)

    def update_local_port(self, lport, original_lport):
        if not self._is_vm_port(lport):
            return

        port_qos_id = self._get_lport_qos_policy_id(lport)
        if (original_lport
                and port_qos_id
                == self._get_lport_qos_policy_id(original_lport)):
            # Do nothing, if the port's qos is the same as db store.
            return

        self._check_update_local_port_qos(lport.get_id(), port_qos_id)

    def _get_lport_qos_policy_id(self, lport):
        """Get the qos policy id from lport or lport's lswitch"""
        if lport.get_qos_policy_id():
            return lport.get_qos_policy_id()

        port_lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        return port_lswitch.get_qos_policy_id()

    def _check_update_local_port_qos(self, lport_id, qos_id):
        if not qos_id:
            # If the there is no qos associated with lport in nb db,
            # the qos in ovs db should also be checked and cleared.
            # This is because the ovs db might not be consistent with
            # nb db.
            self.vswitch_api.clear_port_qos(lport_id)
            return

        qos = self._get_qos_policy(qos_id)
        if not qos:
            LOG.error(_LE("Unable to get QoS %(qos)s when updating QoS of "
                          "local port %(port)s. It may have been deleted."),
                      {'qos': qos_id, 'port': lport_id})
            self.vswitch_api.clear_port_qos(lport_id)
            return

        self._update_local_port_qos(lport_id, qos)

    def _update_local_port_qos(self, port_id, qos):

        def _is_qos_set():
            return qos.get_max_kbps() and qos.get_max_burst_kbps()

        port_ovs_qos = self.vswitch_api.get_port_qos(port_id)
        if port_ovs_qos:
            if _is_qos_set():
                if (port_ovs_qos.get_qos_id() != qos.get_id()
                        or port_ovs_qos.get_version() < qos.get_version()):
                    # The QoS from north is not the same as ovs db.
                    self.vswitch_api.update_port_qos(port_id, qos)
            else:
                # The QoS from north is not set, clear the QoS in ovs db.
                self.vswitch_api.clear_port_qos(port_id)
        else:
            if _is_qos_set():
                self.vswitch_api.set_port_qos(port_id, qos)

    def remove_local_port(self, lport):
        # If removing lport in nb db, the qos in ovs db should also be checked
        # and cleared. This is because the ovs db might not be consistent with
        # nb db.
        self.vswitch_api.delete_port_qos_and_queue(lport.get_id())

    def update_qos_policy(self, qos):
        local_ports = self.db_store.get_local_ports(qos.get_topic())
        for port in local_ports:
            if port.get_qos_policy_id() == qos.get_id():
                self._update_local_port_qos(port.get_id(), qos)

    def delete_qos_policy(self, qos):
        local_ports = self.db_store.get_local_ports(qos.get_topic())
        for port in local_ports:
            if port.get_qos_policy_id() == qos.get_id():
                self.vswitch_api.clear_port_qos(port.get_id())

    def update_logical_switch(self, lswitch, original_lswitch):
        if (original_lswitch and
                lswitch.get_qos_policy_id()
                == original_lswitch.get_qos_policy_id()):
            # Do nothing, if the lswitch's qos is the same as db store.
            return

        local_ports = self.db_store.get_local_ports(lswitch.get_topic())
        for port in local_ports:
            if (port.get_lswitch_id() == lswitch.get_id()
                    and not port.get_qos_policy_id()
                    and self._is_vm_port(port)):
                self._check_update_local_port_qos(port.get_id(),
                                                  lswitch.get_qos_policy_id())

    # TODO(xioahhui): Remove this method, and use method from common utils
    def _is_vm_port(self, lport):
        owner = lport.get_device_owner()
        if not owner or "compute" in owner:
            return True
        return False

    def _get_qos_policy(self, qos_id):
        qos = self.db_store.get_qos_policy(qos_id)
        if not qos:
            qos = self.nb_api.get_qos_policy(qos_id)

        return qos
