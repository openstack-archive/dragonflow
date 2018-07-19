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

from oslo_log import log

from neutron.common import config
from neutron.conf.agent.metadata import config as metadata_conf
from neutron import wsgi

from dragonflow import conf as cfg
from dragonflow.controller.apps import metadata_service
from dragonflow.controller import service as df_service
from dragonflow.db import api_nb

import sys


LOG = log.getLogger(__name__)


def main():
    metadata_conf.register_meta_conf_opts(
        metadata_conf.METADATA_PROXY_HANDLER_OPTS)
    config.init(sys.argv[1:])
    config.setup_logging()
    nb_api = api_nb.NbApi.get_instance()
    service_instance = metadata_service.DFMetadataProxyHandler(
            cfg.CONF, nb_api)
    df_service.register_service('df-metadata-service', nb_api)
    service = wsgi.Server('dragonflow-metadata-service', disable_ssl=True)
    service.start(
        service_instance,
        host=cfg.CONF.df_metadata.ip,
        port=cfg.CONF.df_metadata.port,
    )
    service.wait()
