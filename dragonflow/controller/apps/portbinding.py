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
from dragonflow.controller import port_locator
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2


LOG = log.getLogger(__name__)


class PortBindingApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(PortBindingApp, self).__init__(*args, **kwargs)
        self.switch_features_handler()

    def switch_features_handler(self, ev=None):
        self._local_ports = set()
        self._remote_ports = set()
        port_locator.reset()

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_CREATED)
    def _port_created(self, lport):
        if lport.is_local:
            lport.emit_bind_local()
        elif lport.is_remote:
            lport.emit_bind_remote()

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_UPDATED)
    def _port_updated(self, lport, orig_lport):
        # unbind
        if orig_lport.is_local and not lport.is_local:
            orig_lport.emit_unbind_local()
        elif orig_lport.is_remote and not lport.is_remote:
            orig_lport.emit_unbind_remote()

        if lport.id in self._local_ports:
            lport.emit_local_updated(orig_lport)
        elif lport.id in self._remote_ports:
            lport.emit_remote_updated(orig_lport)

        # bind
        if lport.is_local and not orig_lport.is_local:
            lport.emit_bind_local()
        elif lport.is_remote and not orig_lport.is_remote:
            lport.emit_bind_remote()

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_DELETED)
    def _port_deleted(self, lport):
        if lport.id in self._local_ports:
            lport.emit_unbind_local()
        elif lport.id in self._remote_ports:
            lport.emit_unbind_remote()

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _port_bound_local(self, lport):
        self._local_ports.add(lport.id)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _port_unbound_local(self, lport):
        self._local_ports.remove(lport.id)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    def _port_bound_remote(self, lport):
        self._remote_ports.add(lport.id)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    def _port_unbound_remote(self, lport):
        self._remote_ports.remove(lport.id)
