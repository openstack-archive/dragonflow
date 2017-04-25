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

from dragonflow import conf as cfg
from dragonflow.controller import df_bgp_service
from dragonflow.db.models import bgp
from dragonflow.tests import base as tests_base


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
                               routes=[],
                               ip_version=4)]


class TestDFBGPService(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDFBGPService, self).setUp()
        mock.patch('dragonflow.controller.df_bgp_service.'
                   'BGPService.initialize_driver').start()
        mock_nb_api = mock.patch('dragonflow.db.api_nb.NbApi.get_instance')
        mock_nb_api.start()
        self.addCleanup(mock_nb_api.stop)
        self.bgp_service = df_bgp_service.BGPService()
        self.bgp_service.bgp_driver = mock.Mock()

        iter_models = mock.patch('dragonflow.db.model_framework.iter_models',
                                 return_value={bgp.BGPSpeaker, bgp.BGPPeer})
        iter_models.start()
        self.addCleanup(iter_models.stop)
        self.bgp_service.start()
        self.addCleanup(self.bgp_service.stop)

    def test_sync_bgp_data_to_db_store(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.
        eventlet.sleep(0)

        self.assertTrue(
            self.bgp_service.db_store.get_one(bgp.BGPPeer(id="peer1")))
        self.assertTrue(
            self.bgp_service.db_store.get_one(bgp.BGPSpeaker(id="speaker1")))

    def test_add_remove_bgp_peer_speaker(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.
        eventlet.sleep(0)

        self.bgp_service.bgp_driver.add_bgp_speaker.assert_called_once_with(
            1234)
        self.bgp_service.bgp_driver.add_bgp_peer.assert_called_once_with(
            1234, "172.24.4.88", 4321)

        self.bgp_service.nb_api.get_all.side_effect = lambda x, y: []
        # Give fixed interval another round.
        eventlet.sleep(cfg.CONF.df_bgp.pulse_interval + 1)
        self.bgp_service.bgp_driver.delete_bgp_peer.assert_called_once_with(
            1234, "172.24.4.88")
        self.bgp_service.bgp_driver.delete_bgp_speaker.assert_called_once_with(
            1234)

    def test_advertise_withdraw_routes(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.
        eventlet.sleep(0)

        def get_all_with_routes_side_effect(model, topic):
            if model == bgp.BGPPeer:
                return [bgp.BGPPeer(id="peer1",
                                    topic="topic1",
                                    name="peer1",
                                    peer_ip="172.24.4.88",
                                    remote_as=4321)]

            if model == bgp.BGPSpeaker:
                routes = [{'destination': "10.0.0.0/24",
                           'nexthop': "172.24.4.66"}]
                return [bgp.BGPSpeaker(id="speaker1",
                                       topic="topic1",
                                       name="speaker1",
                                       local_as=1234,
                                       peers=["peer1"],
                                       routes=routes,
                                       ip_version=4)]

        self.bgp_service.nb_api.get_all.side_effect = (
            get_all_with_routes_side_effect)
        # Give fixed interval another round.
        eventlet.sleep(cfg.CONF.df_bgp.pulse_interval + 1)
        self.bgp_service.bgp_driver.advertise_route.assert_called_once_with(
            1234, "10.0.0.0/24", "172.24.4.66")

        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval another round.
        eventlet.sleep(cfg.CONF.df_bgp.pulse_interval + 1)
        self.bgp_service.bgp_driver.withdraw_route.assert_called_once_with(
            1234, "10.0.0.0/24")
