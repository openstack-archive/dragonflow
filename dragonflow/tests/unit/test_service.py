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
import time
import uuid

from jsonmodels import errors

from dragonflow import conf as cfg
from dragonflow.controller import service
from dragonflow.db.models import core
from dragonflow.db.models import service as service_model
from dragonflow.tests import base as tests_base


class TestServiceHealth(tests_base.BaseTestCase):
    def setUp(self):
        super(TestServiceHealth, self).setUp()
        nbapi_patcher = mock.patch('dragonflow.db.api_nb.NbApi')
        self.addCleanup(nbapi_patcher.stop)
        self.nb_api = nbapi_patcher.start()
        self.nb_api.get_instance.return_value = self.nb_api

    def test_init(self):
        with mock.patch.object(service, 'run_status_reporter') as rsr:
            service.register_service('test_binary', self.nb_api)
            self.nb_api.create.assert_called_once_with(service_model.Service(
                    chassis=cfg.CONF.host, binary='test_binary'),
                skip_send_event=True)
            rsr.assert_called_once()

    def test_generate_service_id(self):
        with mock.patch.object(uuid, 'uuid5') as uuid5:
            service_model.generate_service_id('test_host1', 'test_binary')
            uuid5.assert_called_once_with(service_model.SERVICE_ID_NAMESPACE,
                                          'test_host1test_binary')
            uuid5.reset_mock()

            chassis = core.Chassis(id='test_host2')
            service_model.generate_service_id(chassis, 'test_binary')
            uuid5.assert_called_once_with(service_model.SERVICE_ID_NAMESPACE,
                                          'test_host2test_binary')

    def test_on_create_pre(self):
        """
        Verify that the id exists after on_create_pre, and that it is not
        random.
        """
        s = service_model.Service(chassis='test_host1', binary='test_binary')
        self.assertRaises(errors.ValidationError, lambda: s.id)
        s.on_create_pre()
        expected_uuid = str(uuid.uuid5(service_model.SERVICE_ID_NAMESPACE,
                                       'test_host1test_binary'))
        self.assertEqual(expected_uuid, s.id)

    def test_refresh_last_seen(self):
        s = service_model.Service(chassis='test_host1', binary='test_binary')
        self.assertIsNone(s.last_seen_up)
        now = time.time()
        s.refresh_last_seen()
        self.assertLessEqual(now, s.last_seen_up)

    def test_alive(self):
        s = service_model.Service(chassis='test_host1', binary='test_binary')
        timeout = cfg.CONF.df.service_down_time
        s.last_seen_up = 3 * timeout
        with mock.patch.object(time, 'time') as t:
            t.return_value = 3.5 * timeout
            self.assertTrue(s.alive)
            t.return_value = 5 * timeout
            self.assertFalse(s.alive)

    def test_update_last_seen(self):
        s = service_model.Service(chassis='test_host1', binary='test_binary')
        self.nb_api.get.return_value = s
        now = time.time()
        service_model.Service.update_last_seen(self.nb_api,
                                               'test_host1', 'test_binary')
        self.nb_api.update.assert_called_once()
        update_call_args = self.nb_api.update.call_args_list[0]
        updated_service = update_call_args[0][0]
        self.assertLessEqual(now, updated_service.last_seen_up)
        self.assertTrue(update_call_args[1]['skip_send_event'])

    def test_is_alive(self):
        s = service_model.Service(chassis='test_host1', binary='test_binary')
        timeout = cfg.CONF.df.service_down_time
        s.last_seen_up = 3 * timeout
        self.nb_api.get.return_value = s
        with mock.patch.object(time, 'time') as t:
            t.return_value = 3.5 * timeout
            self.assertTrue(service_model.Service.is_alive(
                self.nb_api, 'test_host1', 'test_binary'))
            t.return_value = 5 * timeout
            self.assertFalse(service_model.Service.is_alive(
                self.nb_api, 'test_host1', 'test_binary'))
