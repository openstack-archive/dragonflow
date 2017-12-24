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
from os import path
from oslo_log import log
from oslo_serialization import jsonutils
import stevedore

from dragonflow._i18n import _
from dragonflow import conf as cfg
from dragonflow.controller import app_base
from dragonflow.controller import datapath_layout as dp_layout


LOG = log.getLogger(__name__)

REGS = frozenset((
    'reg0',
    'reg1',
    'reg2',
    'reg3',
    'reg4',
    'reg5',
    'reg6',
    'reg7',
    'metadata',
))


def _sequence_generator(offset):
    while True:
        yield offset
        offset += 1


class Datapath(object):
    """
    Given the layout (e.g. from the config file), instantiate all the
    applications in the datapath (vertices), and connect them (edges).
    Instantiation includes allocating OpenFlow tables and registers.
    Connection includes wiring and mapping the registers
    """
    def __init__(self, layout):
        self._layout = layout
        self._dp_allocs = {}
        self._public_variables = set()
        self.apps = None
        # FIXME(oanson) remove when done porting
        self._dp_allocs[dp_layout.LEGACY_APP] = self._create_legacy_dp_alloc()

    def _create_legacy_dp_alloc(self):
        # Create all possible exits and entries
        table_offset = cfg.CONF.df.datapath_autoalloc_table_offset
        return app_base.DpAlloc(
            states=(),
            entrypoints={str(x): x for x in range(table_offset)},
            exitpoints={str(x): x for x in range(table_offset)},
            full_mapping={
                'source_port_key': 'reg6',
                'destination_port_key': 'reg7',
                'network_key': 'metadata',
            }
        )

    def set_up(self, ryu_base, vswitch_api, nb_api, notifier):
        """
        Instantiate the application classes.
        Instantiate the applications (Including table and register allocation)
        Wire the applications (including translating registers)
        """
        self._dp = ryu_base.datapath
        self._table_generator = _sequence_generator(
            cfg.CONF.df.datapath_autoalloc_table_offset)
        self._public_variables.clear()

        app_classes = {}
        self.apps = {}

        for vertex in self._layout.vertices:
            if vertex.type in app_classes:
                continue

            app_class = self._get_app_class(vertex.type)
            app_classes[vertex.type] = app_class
            self._public_variables.update(
                app_class._specification.public_mapping.keys(),
            )

        for vertex in self._layout.vertices:
            app_class = app_classes[vertex.type]
            dp_alloc = self._create_dp_alloc(app_class._specification)
            self.log_datapath_allocation(vertex.name, dp_alloc)
            self._dp_allocs[vertex.name] = dp_alloc
            app = app_class(api=ryu_base,
                            vswitch_api=vswitch_api,
                            nb_api=nb_api,
                            neutron_server_notifier=notifier,
                            dp_alloc=dp_alloc,
                            **(vertex.params or {})
                            )
            self.apps[vertex.name] = app

        self.write_datapath_allocation()

        for app in self.apps.values():
            app.initialize()

        for edge in self._layout.edges:
            self._install_edge(edge)

    def _get_app_class(self, app_type):
        """Get an application class (Python class) by app name"""
        mgr = stevedore.NamedExtensionManager(
            'dragonflow.controller.apps',
            [app_type],
            invoke_on_load=False,
        )
        for ext in mgr:
            return ext.plugin
        else:
            raise RuntimeError(_('Failed to load app {0}').format(app_type))

    def _create_dp_alloc(self, specification):
        """
        Allocate the tables and registers for the given application (given
        by its specification)
        """
        public_mapping = specification.public_mapping.copy()
        unmapped_vars = self._public_variables.difference(public_mapping)

        # Convert to set() so the result won't be a frozenset()
        unmapped_regs = set(REGS).difference(
            public_mapping.values(),
        ).difference(
            specification.private_mapping.values(),
        )

        while unmapped_vars and unmapped_regs:
            public_mapping[unmapped_vars.pop()] = unmapped_regs.pop()

        if unmapped_vars:
            raise RuntimeError(
                _("Can't allocate enough registers for variables"),
            )

        states_dict = {
            state: next(self._table_generator)
            for state in specification.states
        }
        states = app_base.AttributeDict(**states_dict)

        exitpoints_dict = {
            exit.name: next(self._table_generator)
            for exit in specification.exitpoints
        }
        exitpoints = app_base.AttributeDict(**exitpoints_dict)

        entrypoints_dict = {
            entry.name: states[entry.target]
            for entry in specification.entrypoints
        }
        entrypoints = app_base.AttributeDict(**entrypoints_dict)

        return app_base.DpAlloc(
            states=states,
            exitpoints=exitpoints,
            entrypoints=entrypoints,
            full_mapping=public_mapping,
        )

    def _get_connector_config(self, connector):
        return self._dp_allocs[connector.vertex]

    def _install_edge(self, edge):
        """
        Wire two applications. Infer the translation of metadata fields,
        and install the actions/instructions to pass a packet from one
        application's exit point to another's entry point
        """
        exitpoint = edge.exitpoint
        exit_config = self._get_connector_config(exitpoint)
        entrypoint = edge.entrypoint
        entry_config = self._get_connector_config(entrypoint)
        translations = []

        for var in self._public_variables:
            exit_reg = exit_config.full_mapping[var]
            entry_reg = entry_config.full_mapping[var]
            if exit_reg == entry_reg:
                continue

            translations.append(
                (exit_reg, entry_reg),
            )

        self._install_goto(
            # Source
            exit_config.exitpoints[exitpoint.name],
            # Destination
            entry_config.entrypoints[entrypoint.name],
            translations,
        )

    def _install_goto(self, source, dest, translations):
        """
        Install the actions/instructions to pass a packet from one
        application's exit point to another's entry point, including
        translating the metadata fields.
        """
        ofproto = self._dp.ofproto
        parser = self._dp.ofproto_parser
        actions = []

        try:
            from_regs, to_regs = zip(*translations)
        except ValueError:
            from_regs, to_regs = ((), ())

        # Push all register values
        for reg in from_regs:
            actions.append(
                parser.NXActionStackPush(field=reg, start=0, end=32),
            )

        # Pop into target registers in reverse order
        for reg in reversed(to_regs):
            actions.append(
                parser.NXActionStackPop(field=reg, start=0, end=32),
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

    def log_datapath_allocation(self, name, dp_alloc):
        """
        Log the dp_alloc object (The allocation of tables, registers, etc.) for
        the given application
        """
        LOG.debug("Application: %s", name)
        LOG.debug("\tStates:")
        for state, table_num in dp_alloc.states.items():
            LOG.debug("\t\t%s: %s", state, table_num)

        LOG.debug("\tEntrypoints:")
        for entry_name, table_num in dp_alloc.entrypoints.items():
            LOG.debug("\t\t%s: %s", entry_name, table_num)

        LOG.debug("\tExitpoints:")
        for exit_name, table_num in dp_alloc.exitpoints.items():
            LOG.debug("\t\t%s: %s", exit_name, table_num)

        LOG.debug("\tMapping:")
        for var, reg in dp_alloc.full_mapping.items():
            LOG.debug("\t\t%s: %s", var, reg)

    def write_datapath_allocation(self):
        if not cfg.CONF.df.write_datapath_allocation:
            return
        dppath = cfg.CONF.df.datapath_allocation_output_path
        if (path.isfile(dppath) and
                not cfg.CONF.df.overwrite_datapath_allocation_output_path):
            LOG.warning("File %s exists, but cannot overwrite", dppath)
            return
        try:
            with open(dppath, 'w') as f:
                dp_allocs = self._get_dp_allocs_basic_dictionary()
                jsonutils.dump(dp_allocs, f)
        except IOError:
            LOG.exception("Cannot open file %s", dppath)

    def _get_dp_allocs_basic_dictionary(self):
        return {key: self._dp_alloc_to_dict(value)
                for key, value in self._dp_allocs.items()}

    def _dp_alloc_to_dict(self, dpalloc):
        return {
            'states': dict(dpalloc.states),
            'entrypoints': dict(dpalloc.entrypoints),
            'exitpoints': dict(dpalloc.exitpoints),
            'full_mapping': dict(dpalloc.full_mapping),
        }
