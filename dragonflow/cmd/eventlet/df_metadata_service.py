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

from oslo_config import cfg

from neutron.agent.metadata import config as metadata_conf
from neutron.common import config
from neutron import wsgi

from dragonflow.common import common_params
from dragonflow.controller import metadata_service_app

import sys


def main():
    cfg.CONF.register_opts(metadata_conf.METADATA_PROXY_HANDLER_OPTS)
    cfg.CONF.register_opts(common_params.df_opts, 'df')
    config.init(sys.argv[1:])
    config.setup_logging()
    service = wsgi.Server('dragonflow-metadata-service', disable_ssl=True)
    service.start(
        metadata_service_app.DFMetadataProxyHandler(cfg.CONF),
        port=metadata_service_app.HTTP_PORT,
        host=metadata_service_app.METADATA_SERVICE_IP,
    )
    service.wait()
