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
import stevedore

from dragonflow.controller import app_base
from dragonflow.controller import datapath_layout as dp_layout


def _sequence_generator(offset):
    while True:
        yield offset
        offset += 1


class Datapath(object):
    def __init__(self, layout):
        self._layout = layout
        self._apps = {}  # FIXME may be unneeded
        self._configs = {}
        # FIXME remove when done porting
        self._configs[dp_layout.LEGACY_APP] = self._create_legacy_config()

    def _create_legacy_config(self):
        # Create all possible exits and entries
        return app_base.AppConfig(
            states=(),
            entrypoints={str(x): x for x in range(300)},
            exitpoints={str(x): x for x in range(300)},
        )

    def set_up(self, ryu_base, vswitch_api, nb_api, notifier):
        self._dp = ryu_base.datapath
        self._table_generator = _sequence_generator(300)

        for vertex in self._layout.vertices:
            if vertex.name == dp_layout.LEGACY_APP:
                continue

            app_params = {
                'api': ryu_base,
                'vswitch_api': vswitch_api,
                'nb_api': nb_api,
                'neutron_server_notifier': notifier
            }
            if vertex.params:
                app_params.update(vertex.params)

            app = self._spawn_app(vertex.type, **app_params)
            self._apps[vertex.name] = app

            config = self._create_app_config(app._contract)
            self._configs[vertex.name] = config

            app.set_config(config)
            app.initialize()

        for edge in self._layout.edges:
            self._install_edge(edge)

    def _spawn_app(self, app_type, **kwargs):
        mgr = stevedore.NamedExtensionManager(
            'dragonflow.controller.apps',
            [app_type],
            invoke_on_load=True,
            invoke_kwds=kwargs,
        )
        for ext in mgr:
            return ext.obj

    def _create_app_config(self, contract):
        states = app_base.AttributeDict(
            **{
                state: self._table_generator.next()
                for state in contract.states
            }
        )
        return app_base.AppConfig(
            states=states,
            exitpoints=app_base.AttributeDict(
                **{
                    exit.name: self._table_generator.next()
                    for exit in contract.exitpoints
                }
            ),
            entrypoints=app_base.AttributeDict(
                **{
                    entry.name: states[entry.target]
                    for entry in contract.entrypoints
                }
            ),
        )

    def _get_connector_config(self, connector):
        return self._configs[connector.vertex]

    def _install_edge(self, edge):
        exitpoint = edge.exitpoint
        entrypoint = edge.entrypoint

        self._install_goto(
            # Source
            self._get_connector_config(exitpoint).exitpoints[exitpoint.name],
            # Destination
            self._get_connector_config(entrypoint).entrypoints[entrypoint.name]
        )

    def _install_goto(self, source, dest):
        ofproto = self._dp.ofproto
        parser = self._dp.ofproto_parser

        # FIXME move registers
        if source < dest:
            inst = parser.OFPInstructionGotoTable(dest)
        else:
            inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                [parser.NXActionResubmitTable(table_id=dest)],
            )

        message = parser.OFPFlowMod(
            self._dp,
            table_id=source,
            command=ofproto.OFPFC_ADD,
            match=parser.OFPMatch(),
            instructions=[inst],
        )
        self._dp.send_msg(message)
