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
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app


LOG = log.getLogger(__name__)


class PortQosApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(PortQosApp, self).__init__(*args, **kwargs)
        # qos_version will change in different lifecycle of df controller.
        # So that the old qos in ovs db from last connection can be identified.
        self.qos_version = 0

    def ovs_sync_finished(self):
        # REVISIT(xiaohhui): what if aging app is not enabled?
        self.qos_version = utils.get_aging_cookie()
        old_version = self.qos_version ^ 1
        self.vswitch_api.del_all_qos(old_version)

    def add_local_port(self, lport):
        qos_id = lport.get_qos_policy_id()
        if not qos_id:
            return

        qos = self.db_store.get_qos(qos_id)
        if not qos:
            LOG.error(_LE("Unable to get QoS %s from db store when "
                          "adding local port"), qos_id)
            return

        self.vswitch_api.add_port_qos(lport.get_id(), qos, self.qos_version)

    def update_local_port(self, lport, original_lport):
        new_qos_id = lport.get_qos_policy_id()
        old_qos_id = original_lport.get_qos_policy_id()
        if new_qos_id == old_qos_id:
            return

        if old_qos_id:
            self.vswitch_api.del_port_qos(lport.get_id())

        if new_qos_id:
            qos = self.db_store.get_qos(new_qos_id)
            if not qos:
                LOG.error(_LE("Unable to get QoS %s from db store when "
                              "updating local port"), new_qos_id)
                return
            self.vswitch_api.add_port_qos(
                    lport.get_id(), qos, self.qos_version)

    def remove_local_port(self, lport):
        qos_id = lport.get_qos_policy_id()
        if not qos_id:
            return
        self.vswitch_api.del_qos_and_queue(lport.get_id())

    def update_qos(self, qos):
        local_ports = self.db_store.get_local_ports(qos.get_topic())
        for port in local_ports:
            if port.get_qos_policy_id() == qos.get_id():
                self.vswitch_api.del_port_qos(port.get_id())
                self.vswitch_api.add_port_qos(
                        port.get_id(), qos, self.qos_version)
