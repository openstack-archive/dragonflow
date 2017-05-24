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
from oslo_config import cfg

from dragonflow.common import utils as df_utils
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.tests import base as tests_base
from dragonflow.tests.common import utils


class TestNbApiNeutronNotifier(tests_base.BaseTestCase):

    def setUp(self):
        cfg.CONF.set_override('neutron_notifier',
                              'nb_api_neutron_notifier_driver',
                              group='df')
        mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
                   side_effect=utils.empty_wrapper).start()
        super(TestNbApiNeutronNotifier, self).setUp()
        self.notifier = df_utils.load_driver(
            cfg.CONF.df.neutron_notifier,
            df_utils.DF_NEUTRON_NOTIFIER_DRIVER_NAMESPACE)
        self.notifier.nb_api = mock.Mock()

        getppid_patch = mock.patch('os.getppid', return_value=1)
        self.addCleanup(getppid_patch.stop)
        getppid_patch.start()

    def test_create_new_heart_beat_reporter(self):
        self.notifier.nb_api.get.return_value = None
        self.notifier.create_heart_beat_reporter('fake_host')
        self.notifier.nb_api.register_listener_callback.assert_called_once()

    def test_replace_heart_beat_reporter(self):
        listener = core.Listener(id='fake_host', ppid=6)
        self.notifier.nb_api.get.return_value = listener
        self.notifier.create_heart_beat_reporter('fake_host')
        self.notifier.nb_api.register_listener_callback.assert_called_once()

    def test_valid_heart_beat_reporter_exists(self):
        listener = core.Listener(id='fake_host', ppid=1)
        self.notifier.nb_api.get.return_value = listener
        self.notifier.create_heart_beat_reporter('fake_host')
        self.notifier.nb_api.register_listener_callback.assert_not_called()

    def test_notify_neutron_server(self):
        core_plugin = mock.Mock()
        with mock.patch("neutron_lib.plugins.directory.get_plugin",
                        return_value=core_plugin):
            self.notifier.notify_neutron_server(l2.LogicalPort.table_name,
                                                "fake_port",
                                                "update",
                                                "up")
            core_plugin.update_port_status.assert_called_once_with(
                mock.ANY, "fake_port", "up")
