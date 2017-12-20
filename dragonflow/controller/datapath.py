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
from dragonflow.controller import app_base


def _sequence_generator(offset):
    while True:
        yield offset
        offset += 1


class Datapath(object):
    def __init__(self, app_wiring):
        self._app_wiring = app_wiring
        self._apps = {}
        self._configs = {}

    def set_up(self):
        self._table_generator = _sequence_generator(300)

        for element in self._app_wiring.elements:
            app = self._spawn_app(element)
            self._apps[element.name] = app

            config = self._create_app_config(app._contract)
            self._app_configs[app] = config

            app.set_config(config)
            app.initialize()

        for wire in self._app_wiring.wires:
            self._install_wire(wire)

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

    def _get_connector_app(self, connector):
        return self._apps[connector.element]

    def _install_wire(self, wire):
        endpoint = wire.endpoint
        entrypoint = wire.entrypoint

        self._install_goto(
            # Source
            self._get_connector_app(endpoint).exitpoints[endpoint.connector],
            # Destination
            self._get_connector_app(entrypoint).entrypoints[
                entrypoint.connector
            ],
        )
