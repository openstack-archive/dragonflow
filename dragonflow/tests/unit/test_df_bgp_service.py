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

import threading

import eventlet
from eventlet import greenthread
import mock

from dragonflow.controller import df_bgp_service
from dragonflow.db import api_nb
from dragonflow.db.models import bgp
from dragonflow.tests import base as tests_base


def get_all_side_effect(model, topic=None):
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
                               host_routes=[],
                               prefix_routes=[],
                               ip_version=4)]


class LoopingCallByEvent(object):
    def __init__(self, func):
        self.func = func
        self.thread = None
        self.event = None
        self.is_running = False

    def start(self, *args):
        self.event = threading.Event()
        self.is_running = True
        self.thread = greenthread.spawn(self.run)

    def stop(self):
        self.is_running = False

    def fire(self):
        self.event.set()
        eventlet.sleep(1)

    def run(self):
        self.event.wait()
        while self.is_running:
            self.func()
            self.event.clear()
            self.event.wait()


class TestDFBGPService(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDFBGPService, self).setUp()
        mock.patch('dragonflow.controller.df_bgp_service.'
                   'BGPService.initialize_driver').start()
        mock_nb_api = mock.patch('dragonflow.db.api_nb.NbApi.get_instance')
        mock_nb_api.start()
        self.addCleanup(mock_nb_api.stop)
        nb_api = api_nb.NbApi.get_instance(False)
        self.bgp_service = df_bgp_service.BGPService(nb_api)
        self.bgp_service.bgp_driver = mock.Mock()
        self.bgp_service.bgp_pulse = LoopingCallByEvent(
                self.bgp_service.sync_data_from_nb_db)

        iter_models = mock.patch('dragonflow.db.model_framework.iter_models',
                                 return_value={bgp.BGPSpeaker, bgp.BGPPeer})
        iter_models.start()
        self.addCleanup(iter_models.stop)
        self.bgp_service.start()
        self.addCleanup(self.bgp_service.stop)

    def test_sync_bgp_data_to_db_store(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.
        self.bgp_service.bgp_pulse.fire()

        self.assertTrue(
            self.bgp_service.db_store.get_one(bgp.BGPPeer(id="peer1")))
        self.assertTrue(
            self.bgp_service.db_store.get_one(bgp.BGPSpeaker(id="speaker1")))

    def test_add_remove_bgp_peer_speaker(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.
        self.bgp_service.bgp_pulse.fire()

        self.bgp_service.bgp_driver.add_bgp_speaker.assert_called_once_with(
            1234)
        self.bgp_service.bgp_driver.add_bgp_peer.assert_called_once_with(
            1234, "172.24.4.88", 4321)

        def empty_get_all(model, topic=None):
            return []

        self.bgp_service.nb_api.get_all.side_effect = empty_get_all
        # Give fixed interval another round.
        self.bgp_service.bgp_pulse.fire()
        self.bgp_service.bgp_driver.delete_bgp_peer.assert_called_once_with(
            1234, "172.24.4.88")
        self.bgp_service.bgp_driver.delete_bgp_speaker.assert_called_once_with(
            1234)

    def test_advertise_withdraw_routes(self):
        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        # Give fixed interval a chance to run.

        def get_all_with_routes_side_effect(model, topic=None):
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
                                       prefix_routes=routes,
                                       host_routes=[],
                                       ip_version=4)]

        self.bgp_service.nb_api.get_all.side_effect = (
            get_all_with_routes_side_effect)

        self.bgp_service.bgp_pulse.fire()

        self.bgp_service.bgp_driver.advertise_route.assert_called_once_with(
            1234, "10.0.0.0/24", "172.24.4.66")

        self.bgp_service.nb_api.get_all.side_effect = get_all_side_effect
        self.bgp_service.bgp_pulse.fire()
        self.bgp_service.bgp_driver.withdraw_route.assert_called_once_with(
            1234, "10.0.0.0/24")
