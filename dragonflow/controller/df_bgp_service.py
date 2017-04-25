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
import sys

from neutron.common import config as common_config
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_service import service
from oslo_utils import importutils

from dragonflow import conf as cfg
from dragonflow.controller import df_db_objects_refresh
from dragonflow.db import api_nb
from dragonflow.db import db_store2
from dragonflow.db import model_framework
from dragonflow.db.models import bgp  # noqa


LOG = logging.getLogger(__name__)


class BGPService(service.Service):
    def __init__(self):
        super(BGPService, self).__init__()
        self.initialize_driver()
        self.db_store = db_store2.get_instance()

        # BGP dynamic route is not a service that needs real time response.
        # So disable pubsub here and use period task to do BGP job.
        cfg.CONF.set_override('enable_df_pub_sub', False, group='df')
        self.nb_api = api_nb.NbApi.get_instance(False)

        self.bgp_pulse = loopingcall.FixedIntervalLoopingCall(
            self.sync_data_from_nb_db)

    def initialize_driver(self):
        try:
            self.bgp_driver = (
                importutils.import_object(cfg.CONF.df_bgp.bgp_speaker_driver,
                                          cfg.CONF.df_bgp))
        except ImportError:
            LOG.exception("Error while importing BGP speaker driver %s",
                          cfg.CONF.df_bgp.bgp_speaker_driver)
            raise SystemExit(1)

    def start(self):
        super(BGPService, self).start()
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.register_bgp_models()
        self.bgp_pulse.start(cfg.CONF.df_bgp.pulse_interval)

    def stop(self):
        super(BGPService, self).stop()
        self.bgp_pulse.stop()

    def register_bgp_models(self):
        for model in model_framework.iter_models_by_dependency_order():
            df_db_objects_refresh.add_refresher(
                df_db_objects_refresh.DfObjectRefresher(
                    model.__name__,
                    functools.partial(self.db_store.get_keys_by_topic,
                                      model),
                    functools.partial(self.nb_api.get_all, model),
                    self.update_model_object,
                    functools.partial(self.delete_model_object, model),
                ),
            )

    def sync_data_from_nb_db(self):
        df_db_objects_refresh.sync_local_cache_from_nb_db()

    def update_model_object(self, obj):
        original_obj = self.db_store.get_one(obj)
        getattr(self, "update_" + obj.table_name)(obj, original_obj)
        self.db_store.update(obj)

    def delete_model_object(self, model, obj_id):
        obj = self.db_store.get_one(model(id=obj_id))
        LOG.info("Delete %(table)s with data %(data)s.",
                 {'table': obj.table_name, 'data': obj})
        getattr(self, "delete_" + obj.table_name)(obj)
        self.db_store.delete(obj)

    def update_bgp_peer(self, peer, original_peer=None):
        # Nothing to do when update bgp peer.
        pass

    def delete_bgp_peer(self, peer):
        # TODO(xiaohhui): Neutron allows delete bgp peers that are still used
        # by speaker. Need to clear the peer in speaker in nb db and delete
        # peer by using bgp_driver.
        pass

    def update_bgp_speaker(self, speaker, original_speaker=None):
        if speaker == original_speaker:
            return

        LOG.info("Create/Update %(table)s with data %(data)s.",
                 {'table': speaker.table_name, 'data': speaker})

        if not original_speaker:
            self.bgp_driver.add_bgp_speaker(speaker.local_as)

        old_peers = original_speaker.peers if original_speaker else []
        new_peers = speaker.peers
        old_routes = original_speaker.routes if original_speaker else []
        new_routes = speaker.routes

        # Delete stale peers, note that deleting bgp peer will close the bgp
        # connection between peer and local speaker, and routes in remote peer
        # will be cleared. So no need to clear routes before deleting bgp peer
        for p in old_peers:
            if p not in new_peers:
                self.bgp_driver.delete_bgp_peer(speaker.local_as,
                                                str(p.peer_ip))

        # Add new peers
        for p in new_peers:
            if p not in old_peers:
                self.bgp_driver.add_bgp_peer(speaker.local_as,
                                             str(p.peer_ip), p.remote_as)

        # Withdraw routes
        for r in old_routes:
            if r not in new_routes:
                self.bgp_driver.withdraw_route(speaker.local_as,
                                               str(r.destination))

        # Advertise routes
        for r in new_routes:
            if r not in old_routes:
                self.bgp_driver.advertise_route(speaker.local_as,
                                                str(r.destination),
                                                str(r.nexthop))

    def delete_bgp_speaker(self, speaker):
        peers = speaker.peers

        # Delete stale peers
        for p in peers:
            self.bgp_driver.delete_bgp_peer(speaker.local_as, str(p.peer_ip))

        self.bgp_driver.delete_bgp_speaker(speaker.local_as)


def main():
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    server = BGPService()
    service.launch(cfg.CONF, server).wait()
