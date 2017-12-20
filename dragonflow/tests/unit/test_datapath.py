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
import functools

import mock
import testscenarios

from dragonflow.controller import app_base
from dragonflow.controller import datapath
from dragonflow.controller import datapath_layout
from dragonflow.tests import base as tests_base

load_tests = testscenarios.load_tests_apply_scenarios


@app_base.define_specification(
    states=('main',),
    entrypoints=(
        app_base.Entrypoint(
            name='conn1',
            target='main',
            consumes={},
        ),
        app_base.Entrypoint(
            name='conn2',
            target='main',
            consumes={},
        ),
    ),
    exitpoints=(
        app_base.Exitpoint(
            name='conn1',
            provides={},
        ),
        app_base.Exitpoint(
            name='conn2',
            provides={},
        ),
    ),
    public_mapping={
        'var1': 'reg0',
        'var2': 'reg1',
        'var3': 'reg2',
    },
    private_mapping={
        'priv1': 'reg3',
        'priv2': 'reg7',
    }
)
class DummyApp(app_base.Base):
    def __init__(self, *args, **kwargs):
        # super(DummyApp, self).__init__(*args, **kwargs)
        self.args = args
        self.kwargs = kwargs


@app_base.define_specification(
    states=('main',),
    entrypoints=(
        app_base.Entrypoint(
            name='conn1',
            target='main',
            consumes={},
        ),
        app_base.Entrypoint(
            name='conn2',
            target='main',
            consumes={},
        ),
    ),
    exitpoints=(
        app_base.Exitpoint(
            name='conn1',
            provides={},
        ),
        app_base.Exitpoint(
            name='conn2',
            provides={},
        ),
    ),
    public_mapping={
        'var1': 'reg0',
        'var3': 'reg1',
    },
    private_mapping={
        'priv1': 'reg2',
        'priv2': 'reg7',
    }
)
class Dummy2App(DummyApp):
    pass


class TestDatapath(tests_base.BaseTestCase):
    scenarios = [
        (
            'empty-config',
            {
                'layout': datapath_layout.Layout(
                    vertices=(),
                    edges=(),
                ),
                'raises': None,
            },
        ),
        (
            'non-existent-vertex',
            {
                'layout': datapath_layout.Layout(
                    vertices=(),
                    edges=(
                        datapath_layout.Edge(
                            exitpoint=datapath_layout.Connector(
                                'app1', 'out', 'conn1',
                            ),
                            entrypoint=datapath_layout.Connector(
                                'app2', 'out', 'conn1',
                            ),
                        ),
                    ),
                ),
                'raises': KeyError,
            },
        ),
        (
            'connected-vertices',
            {
                'layout': datapath_layout.Layout(
                    vertices=(
                        datapath_layout.Vertex(
                            name='app1',
                            type='dummy',
                            params={'key1': 'val1'},
                        ),
                        datapath_layout.Vertex(
                            name='app2',
                            type='dummy2',
                            params={'key2': 'val2'},
                        ),
                    ),
                    edges=(
                        datapath_layout.Edge(
                            exitpoint=datapath_layout.Connector(
                                'app1', 'out', 'conn1',
                            ),
                            entrypoint=datapath_layout.Connector(
                                'app2', 'in', 'conn1',
                            ),
                        ),
                    ),
                ),
                'raises': None,
            },
        ),
    ]

    def get_dummy_class(self, type):
        if type == 'dummy':
            return DummyApp
        else:
            return Dummy2App

    def setUp(self):
        super(TestDatapath, self).setUp()
        self.dp = datapath.Datapath(self.layout)
        self.dp._get_app_class = mock.Mock(side_effect=self.get_dummy_class)
        self.dp._install_goto = mock.Mock()

    def test_set_up(self):
        if self.raises:
            caller = functools.partial(
                self.assertRaises,
                self.raises,
            )
        else:
            def caller(func, *args):
                func(*args)

        caller(
            self.dp.set_up,
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
        )

    def test_app_initialization(self):
        if self.raises is not None:
            raise self.skipTest('Tests only positive flows')

        self.dp.set_up(
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
        )
        self.assertEqual(
            len(self.layout.vertices),
            self.dp._get_app_class.call_count,
        )

    def test_installed_gotos(self):
        if self.raises is not None:
            raise self.skipTest('Tests only positive flows')

        self.dp.set_up(
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
            mock.Mock(),
        )
        self.assertEqual(
            len(self.layout.edges),
            self.dp._install_goto.call_count,
        )
        # FIXME add check for actual call parameters
