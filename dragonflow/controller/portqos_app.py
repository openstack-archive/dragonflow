# Copyright (c) 2015 OpenStack Foundation.
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

from dragonflow._i18n import _LE
from dragonflow.controller.df_base_app import DFlowApp

from neutron.agent.common import config

from oslo_log import log

config.setup_logging()
LOG = log.getLogger(__name__)


class PortQosApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(PortQosApp, self).__init__(*args, **kwargs)
        self.vswitch_api = kwargs['vswitch_api']
        self.db_store = kwargs['db_store']

    def add_local_port(self, lport):
        qos_id = lport.get_qos()
        if not qos_id:
            return

        qos = self.db_store.get_qos(qos_id)
        if not qos:
            LOG.error(_LE("Get qos %s from db store when"
                          "adding local port, but it is none"), qos_id)
            return

        self.vswitch_api.add_port_qos(lport.get_id(), qos)

    def update_local_port(self, lport, original_lport):
        new_qos_id = lport.get_qos()
        old_qos_id = original_lport.get_qos()
        if not new_qos_id:
            if not old_qos_id:
                return
            else:
                self.vswitch_api.del_port_qos(lport.get_id())
        else:
            qos = self.db_store.get_qos(new_qos_id)
            if not qos:
                LOG.error(_LE("Get new qos %s from db store"
                              "when updating local port, but it"
                              "is none"), new_qos_id)
                return
            if old_qos_id:
                if old_qos_id == new_qos_id:
                    return
                self.vswitch_api.del_port_qos(lport.get_id())
            self.vswitch_api.add_port_qos(lport.get_id(), qos)

    def remove_local_port(self, lport):
        qos_id = lport.get_qos()
        if not qos_id:
            return
        self.vswitch_api.del_port_qos(lport.get_id())

    def update_qos(self, qos):
        local_ports = self.db_store.get_local_ports(qos.get_topic())
        for port in local_ports:
            if port.get_qos() == qos.get_id():
                self.vswitch_api.del_port_qos(port.get_id())
                self.vswitch_api.add_port_qos(port.get_id(), qos)
