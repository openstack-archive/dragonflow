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

import eventlet
import mock

from dragonflow.controller import df_bgp_service
from dragonflow.db.models import bgp
from dragonflow.tests import base as tests_base


class TestDFBGPService(tests_base.BaseTestCase):

    @mock.patch('dragonflow.db.api_nb.NbApi.get_instance')
    def test_sync_bgp_data_to_db_store(self, get_instance):
        bgp_service = df_bgp_service.BGPService()

        def get_all_side_effect(model, topic):
            if model == bgp.BGPPeer:
                return [bgp.BGPPeer(id="peer1",
                                    topic="topic1",
                                    name="peer1",
                                    peer_ip="172.24.4.88",
                                    remote_as=4321)]

            if model == bgp.BGPSpeaker:
                return [bgp.BGPSpeaker(id="speaker1",
                                       topic="topic1",
                                       name="speaker1",
                                       local_as=1234,
                                       peers=["peer1"],
                                       ip_version=4)]

        bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        with mock.patch('dragonflow.db.model_framework.iter_models',
                        return_value={bgp.BGPSpeaker, bgp.BGPPeer}):
            bgp_service.start()
            self.addCleanup(bgp_service.stop)
            # Give fixed interval a chance to run.
            eventlet.sleep(0)
            self.assertTrue(
                bgp_service.db_store.get_one(bgp.BGPPeer(id="peer1")))
            self.assertTrue(
                bgp_service.db_store.get_one(bgp.BGPSpeaker(id="speaker1")))
