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


# Specify the states, entrypoints, exitpoints, public mappings and private
# mappings of an application:
# States - the number of states the application has (Translates to number of
#          OpenFlow tables)
# Entrypoints - Where do packets come in?
# Exitpoints - Where do packets come out?
# Public Mappings - Metadata that is passed between applications
# Private Mappings - Metadata that is private to this application (e.g. to save
#                    a state accross tables)
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


# Entrypoint: An entrypoint for packets - The application accepts packets here,
# and they should be routed to the given target (or OpenFlow table).
# consumes: Which metadata is consumbed by this entrypoint.
Entrypoint = collections.namedtuple(
    'Entrypoint',
    ('name', 'target', 'consumes'),
)


# Exitpoint: An exitpoint for packets - The application sends (resubmits, or
# gotos) packets to this table (provided by the framework).
# provides: Which metadata is set on the packet
Exitpoint = collections.namedtuple(
    'Exitpoint',
    ('name', 'provides'),
)


# The allocation of states (table numbers), entrypoints and exitpoints (tables
# for incoming and outgoing packets), and register mapping (where to place
# the metadata)
DpAlloc = collections.namedtuple(
    'DpAlloc',
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

    @property
    def entrypoints(self):
        return self._dp_alloc.entrypoints


register_event = df_base_app.register_event
