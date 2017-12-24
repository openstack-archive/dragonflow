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

LEGACY_APP = 'dragonflow-legacy'


Vertex = collections.namedtuple(
    'Vertex',
    ('name', 'type', 'params'),
)


Edge = collections.namedtuple(
    'Edge',
    ('exitpoint', 'entrypoint'),
)


class Connector(
    collections.namedtuple(
        'Connector',
        ('vertex', 'type', 'name'),
    ),
):
    @classmethod
    def from_string(cls, val):
        return cls(*val.split(':'))


DatapathLayout = collections.namedtuple(
    'DatapathLayout',
    ('vertices', 'edges'),
)


def get_datapath_layout():
    return DatapathLayout(
        vertices=(
            Vertex(
                name=LEGACY_APP,
                type=LEGACY_APP,
                params={},
            ),
            Vertex(
                name='portsec',
                type='portsec',
                params={},
            ),
        ),
        edges=(
            Edge(
                exitpoint=Connector.from_string('dragonflow-legacy:out:5'),
                entrypoint=Connector.from_string('portsec:in:default'),
            ),
            Edge(
                exitpoint=Connector.from_string('portsec:out:default'),
                entrypoint=Connector.from_string('dragonflow-legacy:out:10'),
            ),
            Edge(
                exitpoint=Connector.from_string('portsec:out:services'),
                entrypoint=Connector.from_string('dragonflow-legacy:out:20'),
            ),
        ),
    )
