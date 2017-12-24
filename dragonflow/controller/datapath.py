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

REGS = (
    'reg0',
    'reg1',
    'reg2',
    'reg3',
    'reg4',
    'reg5',
    'reg6',
    'reg7',
    'metadata',
)


def _sequence_generator(offset):
    while True:
        yield offset
        offset += 1


class Datapath(object):
    def __init__(self, layout):
        self._layout = layout
        self._apps = {}  # FIXME may be unneeded
        self._configs = {}
        self._public_variables = set()
        # FIXME remove when done porting
        self._configs[dp_layout.LEGACY_APP] = self._create_legacy_config()

    def _create_legacy_config(self):
        # Create all possible exits and entries
        return app_base.AppConfig(
            states=(),
            entrypoints={str(x): x for x in range(200)},
            exitpoints={str(x): x for x in range(200)},
            full_mapping={
                'source_port_key': 'reg6',
                'destination_port_key': 'reg7',
                'router_key': 'reg5',
                'network_key': 'metadata',
            }
        )

    def set_up(self, ryu_base, vswitch_api, nb_api, notifier):
        self._dp = ryu_base.datapath
        self._table_generator = _sequence_generator(200)
        self._public_variables.clear()

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
            self._public_variables.update(
                set(app._contract.public_mapping.keys()),
            )

        for name, app in self._apps.items():
            config = self._create_app_config(app._contract)
            self._configs[name] = config
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
        mapping = contract.public_mapping.copy()
        unmapped_vars = self._public_variables.difference(mapping)
        unmapped_regs = set(REGS).difference(
            mapping.values(),
        ).difference(
            contract.private_mapping.values(),
        )

        while unmapped_vars and unmapped_regs:
            mapping[unmapped_vars.pop()] = unmapped_regs.pop()

        if unmapped_vars:
            raise RuntimeError("Can't allocate enough registers for variables")

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
            full_mapping=mapping,
        )

    def _get_connector_config(self, connector):
        return self._configs[connector.vertex]

    def _install_edge(self, edge):
        exitpoint = edge.exitpoint
        exit_config = self._get_connector_config(exitpoint)
        entrypoint = edge.entrypoint
        entry_config = self._get_connector_config(entrypoint)
        translations = []
        map = {}

        for var in self._public_variables:
            exit_reg = exit_config.full_mapping[var]
            entry_reg = entry_config.full_mapping[var]
            if exit_reg == entry_reg:
                continue

            # Find current location of exit_reg, may have been moved by a prev
            # translation
            while exit_reg in map:
                exit_reg = map[exit_reg]

            # TODO (dimak) current add_goto swaps regs with stack, we can do
            # better by finding by using graphs and finding cycles.
            translations.append(
                (exit_reg, entry_reg),
            )
            map[entry_reg] = exit_reg

        self._install_goto(
            # Source
            exit_config.exitpoints[exitpoint.name],
            # Destination
            entry_config.entrypoints[entrypoint.name],
            translations,
        )

    def _install_goto(self, source, dest, translations):
        ofproto = self._dp.ofproto
        parser = self._dp.ofproto_parser

        actions = []
        for src_reg, dst_reg in translations:
            actions.extend(
                (
                    parser.NXActionStackPush(field=dst_reg, start=0, end=31),
                    parser.NXActionRegMove(src_field=src_reg,
                                           dst_field=dst_reg,
                                           n_bits=32),
                    parser.NXActionStackPop(field=src_reg, start=0, end=31),
                ),
            )

        if source < dest:
            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    actions,
                ),
                parser.OFPInstructionGotoTable(dest),
            ]
        else:
            actions.append(parser.NXActionResubmitTable(table_id=dest))

            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    actions,
                ),
            ]

        message = parser.OFPFlowMod(
            self._dp,
            table_id=source,
            command=ofproto.OFPFC_ADD,
            match=parser.OFPMatch(),
            instructions=instructions,
        )
        self._dp.send_msg(message)
