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

import os

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from dragonflow.common import utils as df_utils
from dragonflow.db import models
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

    def test_create_heart_beat_reporter(self):
        nb_api = mock.Mock()
        self.notifier.nb_api = nb_api
        nb_api.get_neutron_listener.return_value = None
        self.notifier.create_heart_beat_reporter('fake_host')
        self.assertTrue(nb_api.register_listener_callback.called)

        nb_api.reset_mock()
        listener = {'id': 'fake_host', 'ppid': 'fake_ppid'}
        nb_api.get_neutron_listener.return_value = models.Listener(
                                                    jsonutils.dumps(listener))
        self.notifier.create_heart_beat_reporter('fake_host')
        self.assertTrue(nb_api.register_listener_callback.called)

        nb_api.reset_mock()
        listener = {'id': 'fake_host', 'ppid': os.getppid()}
        nb_api.get_neutron_listener.return_value = models.Listener(
                                                    jsonutils.dumps(listener))
        self.notifier.create_heart_beat_reporter('fake_host')
        self.assertFalse(nb_api.register_listener_callback.called)

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
