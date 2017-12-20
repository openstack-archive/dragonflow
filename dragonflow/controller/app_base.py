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


Specification = collections.namedtuple(
    'Specification',
    ('states', 'entrypoints', 'exitpoints', 'public_mapping',
     'private_mapping'),
)


def define_specification(states, entrypoints, exitpoints,
                         public_mapping=None, private_mapping=None):
    if public_mapping is None:
        public_mapping = {}

    if private_mapping is None:
        private_mapping = {}

    def decorator(cls):
        cls._specification = Specification(
            states=states,
            entrypoints=entrypoints,
            exitpoints=exitpoints,
            public_mapping=public_mapping,
            private_mapping=private_mapping,
        )
        return cls

    return decorator


Entrypoint = collections.namedtuple(
    'Entrypoint',
    ('name', 'target', 'consumes'),
)


Exitpoint = collections.namedtuple(
    'Exitpoint',
    ('name', 'provides'),
)

DpAlloc = collections.namedtuple(
    'DpAlloc',  # FIXME (dimak) find a better name
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
    def __init__(self, dp_alloc, *args, **kwargs):
        super(Base, self).__init__(*args, **kwargs)
        self._dp_alloc = dp_alloc

    def initialize(self):
        pass

    @property
    def states(self):
        return self._dp_alloc.states

    @property
    def exitpoints(self):
        return self._dp_alloc.exitpoints


register_event = df_base_app.register_event
