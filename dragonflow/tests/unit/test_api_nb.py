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

from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.tests import base as tests_base


class TestNbApi(tests_base.BaseTestCase):
    def setUp(self):
        super(TestNbApi, self).setUp()
        self.api_nb = api_nb.NbApi(
            db_driver=mock.Mock(),
            use_pubsub=True,
            is_neutron_server=True
        )
        self.api_nb.publisher = mock.Mock()
        self.api_nb.enable_selective_topo_dist = True

    def test_topicless_send_event(self):
        self.api_nb._send_db_change_event('table', 'key', 'action',
                                          'value', None)
        self.api_nb.publisher.send_event.assert_called()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]
        self.assertEqual(db_common.SEND_ALL_TOPIC, update.topic)

    def test_send_event_with_topic(self):
        self.api_nb._send_db_change_event('table', 'key', 'action',
                                          'value', 'topic')
        self.api_nb.publisher.send_event.assert_called()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]
        self.assertEqual('topic', update.topic)
