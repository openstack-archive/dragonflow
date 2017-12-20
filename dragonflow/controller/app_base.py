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
import collections

from dragonflow.controller import df_base_app


def define_contract(states, entrypoints, exitpoints,
                    public_mapping=None, private_mapping=None):
    if public_mapping is None:
        public_mapping = {}

    if private_mapping is None:
        private_mapping = {}

    def decorator(cls):
        cls._contract = Contract(
            states=states,
            entrypoints=entrypoints,
            exitpoints=exitpoints,
            public_mapping=public_mapping,
            private_mapping=private_mapping,
        )
        return cls

    return decorator


Contract = collections.namedtuple(
    'Contract',
    ('states', 'entrypoints', 'exitpoints', 'public_mapping',
     'private_mapping'),
)


Entrypoint = collections.namedtuple(
    'Entrypoint',
    ('name', 'target', 'consumes'),
)


Exitpoint = collections.namedtuple(
    'Exitpoint',
    ('name', 'provides'),
)

AppConfig = collections.namedtuple(
    'AppConfig',  # FIXME
    ('states', 'exitpoints', 'entrypoints', 'full_mapping'),
)


class VariableMapping(dict):
    pass


class AttributeDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class Base(df_base_app.DFlowApp):
    def initialize(self):
        pass

    def set_config(self, app_config):
        self._app_config = app_config
        self.states = app_config.states
        self.exitpoints = app_config.exitpoints

    def switch_features_handler(self, ev):
        self.initialize()


register_event = df_base_app.register_event
