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

import mock

from dragonflow.db.models import l2
from dragonflow.tests.unit import test_app_base


def mock_with_name():
    m = mock.Mock()
    m.__name__ = m.__module__ = 'mock'
    return m


# Holds all event mocks
_M = {}


class TestPortBindingApp(test_app_base.DFAppTestBase):
    apps_list = ['portbinding']

    def setUp(self):
        super(TestPortBindingApp, self).setUp()
        self._app = self.open_flow_app.dispatcher.apps['portbinding']

        for event in (
            l2.EVENT_BIND_LOCAL,
            l2.EVENT_BIND_REMOTE,
            l2.EVENT_LOCAL_UPDATED,
            l2.EVENT_REMOTE_UPDATED,
            l2.EVENT_UNBIND_LOCAL,
            l2.EVENT_UNBIND_REMOTE,
        ):
            m = mock_with_name()
            l2.LogicalPort.register(event, m)
            _M[event] = m

    def test_local_port_created(self):
        port = test_app_base.make_fake_local_port()
        port.emit_created()
        _M[l2.EVENT_BIND_LOCAL].assert_called_once_with(port)

    def test_local_remote_created(self):
        port = test_app_base.make_fake_remote_port()
        port.emit_created()
        _M[l2.EVENT_BIND_REMOTE].assert_called_once_with(port)

    def test_local_port_deleted(self):
        port = test_app_base.make_fake_local_port()
        port.emit_created()
        port.emit_deleted()
        _M[l2.EVENT_UNBIND_LOCAL].assert_called_once_with(port)

    def test_remote_port_deleted(self):
        port = test_app_base.make_fake_remote_port()
        port.emit_created()
        port.emit_deleted()
        _M[l2.EVENT_UNBIND_REMOTE].assert_called_once_with(port)

    def test_update_local_port(self):
        port = test_app_base.make_fake_local_port()
        port.emit_created()
        port.emit_updated(port)
        _M[l2.EVENT_LOCAL_UPDATED].assert_called_once_with(port, port)

    def test_update_remote_port(self):
        port = test_app_base.make_fake_remote_port()
        port.emit_created()
        port.emit_updated(port)
        _M[l2.EVENT_REMOTE_UPDATED].assert_called_once_with(port, port)

    def test_update_unbind_local(self):
        old_port = test_app_base.make_fake_local_port(id='id1')
        new_port = test_app_base.make_fake_port(id='id1')
        old_port.emit_created()
        new_port.emit_updated(old_port)
        _M[l2.EVENT_UNBIND_LOCAL].assert_called_once_with(old_port)
        _M[l2.EVENT_LOCAL_UPDATED].assert_not_called()

    def test_update_unbind_remote(self):
        old_port = test_app_base.make_fake_remote_port(id='id1')
        new_port = test_app_base.make_fake_port(id='id1')
        old_port.emit_created()
        new_port.emit_updated(old_port)
        _M[l2.EVENT_UNBIND_REMOTE].assert_called_once_with(old_port)
        _M[l2.EVENT_REMOTE_UPDATED].assert_not_called()

    def test_update_bind_local(self):
        old_port = test_app_base.make_fake_port(id='id1')
        new_port = test_app_base.make_fake_local_port(id='id1')
        old_port.emit_created()
        new_port.emit_updated(old_port)
        _M[l2.EVENT_BIND_LOCAL].assert_called_once_with(new_port)
        _M[l2.EVENT_LOCAL_UPDATED].assert_not_called()

    def test_update_bind_remote(self):
        old_port = test_app_base.make_fake_port(id='id1')
        new_port = test_app_base.make_fake_remote_port(id='id1')
        old_port.emit_created()
        new_port.emit_updated(old_port)
        _M[l2.EVENT_BIND_REMOTE].assert_called_once_with(new_port)
        _M[l2.EVENT_REMOTE_UPDATED].assert_not_called()
