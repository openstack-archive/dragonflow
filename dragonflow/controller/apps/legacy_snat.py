# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log

from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l3

LOG = log.getLogger(__name__)


class LegacySNatApp(df_base_app.DFlowApp):

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_CREATED)
    def router_created(self, router):
        for new_port in router.ports:
            self._add_router_port(new_port)

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_UPDATED)
    def router_updated(self, router, orig_router):
        new_ports = {port.id: port for port in router.ports}
        for old_port in orig_router.ports:
            new_port = new_ports.pop(old_port.id, None)
            if old_port == new_port:
                continue
            self._delete_router_port(old_port)
            # Very unlikely case. router ports are immutable in Neutron
            if new_port:
                new_ports[new_port.id] = new_port

        # Add ports only after all old ones were removed to avoid collision
        for new_port in new_ports.values():
            self._add_router_port(new_port)

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_DELETED)
    def router_deleted(self, router):
        for port in router.ports:
            self._delete_router_port(port)

    def _add_router_port(self, router_port):
        lswitch = router_port.lswitch
        network_id = lswitch.unique_key
        mac = router_port.mac
        tunnel_key = router_port.unique_key
        ofproto = self.ofproto
        parser = self.parser
        match = parser.OFPMatch(metadata=network_id, eth_dst=mac)
        actions = [parser.OFPActionSetField(reg7=tunnel_key)]
        inst = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            parser.OFPInstructionGotoTable(const.EGRESS_TABLE),
        ]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)

    def _delete_router_port(self, router_port):
        lswitch = router_port.lswitch
        network_id = lswitch.unique_key
        mac = router_port.mac
        ofproto = self.ofproto
        parser = self.parser
        match = parser.OFPMatch(metadata=network_id, eth_dst=mac)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)
