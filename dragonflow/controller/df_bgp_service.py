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
from oslo_service import loopingcall
from oslo_service import service

from dragonflow import conf as cfg
from dragonflow.controller import df_db_objects_refresh
from dragonflow.db import api_nb
from dragonflow.db import db_store2
from dragonflow.db import model_framework
from dragonflow.db.models import bgp  # noqa


class BGPService(service.Service):
    def __init__(self):
        super(BGPService, self).__init__()
        self.db_store = db_store2.get_instance()

        # BGP dynamic route is not a service that needs real time response.
        # So disable pubsub here and use period task to do BGP job.
        cfg.CONF.set_override('enable_df_pub_sub', False, group='df')
        self.nb_api = api_nb.NbApi.get_instance(False)

        self.bgp_pulse = loopingcall.FixedIntervalLoopingCall(
            self.sync_data_from_nb_db)

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
        self.db_store.update(obj)

    def delete_model_object(self, model, obj_id):
        self.db_store.delete(model(id=obj_id))


def main():
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    server = BGPService()
    service.launch(cfg.CONF, server).wait()
