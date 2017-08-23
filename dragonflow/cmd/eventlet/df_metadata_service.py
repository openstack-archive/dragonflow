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

from neutron.agent.common import utils
from neutron.agent.linux import ip_lib
from neutron.common import config
from neutron.conf.agent.metadata import config as metadata_conf
from neutron import wsgi

from dragonflow import conf as cfg
from dragonflow.controller.apps import metadata_service
from dragonflow.controller import service as df_service
from dragonflow.db import api_nb

import sys


LOG = log.getLogger(__name__)

METADATA_ROUTE_TABLE_ID = '2'


def environment_setup():
    bridge = cfg.CONF.df.integration_bridge
    interface = cfg.CONF.df_metadata.metadata_interface
    port = cfg.CONF.df_metadata.port
    if ip_lib.device_exists(interface):
        LOG.info("Device %s already exists", interface)
        # Destroy the environment when the device exists.
        # We can re-initialize the environment correctly.
        environment_destroy()

    cmd = ["ovs-vsctl", "add-port", bridge, interface,
           "--", "set", "Interface", interface, "type=internal"]
    utils.execute(cmd, run_as_root=True)

    ip = cfg.CONF.df_metadata.ip
    cmd = ["ip", "addr", "add", "dev", interface, "{}/0".format(ip)]
    utils.execute(cmd, run_as_root=True)

    cmd = ["ip", "link", "set", "dev", interface, "up"]
    utils.execute(cmd, run_as_root=True)

    cmd = ["ip", "route", "add", "0.0.0.0/0", "dev", interface,
           "table", METADATA_ROUTE_TABLE_ID]
    utils.execute(cmd, run_as_root=True)

    cmd = ["ip", "rule", "add", "from", ip, "table", METADATA_ROUTE_TABLE_ID]
    utils.execute(cmd, run_as_root=True)

    cmd = ["iptables", '-I', 'INPUT', '-i', interface, '-p', 'tcp', '--dport',
           str(port), '-j', 'ACCEPT']
    utils.execute(cmd, run_as_root=True)


def environment_destroy():
    bridge = cfg.CONF.df.integration_bridge
    interface = cfg.CONF.df_metadata.metadata_interface
    cmd = ["ovs-vsctl", "del-port", bridge, interface]
    utils.execute(cmd, run_as_root=True, check_exit_code=[0])

    ip = cfg.CONF.df_metadata.ip
    cmd = ["ip", "rule", "del", "from", ip, "table", METADATA_ROUTE_TABLE_ID]
    utils.execute(cmd, run_as_root=True)


def main():
    metadata_conf.register_meta_conf_opts(
        metadata_conf.METADATA_PROXY_HANDLER_OPTS)
    config.init(sys.argv[1:])
    config.setup_logging()
    environment_setup()
    cfg.CONF.set_override('enable_df_pub_sub', False, group='df')
    nb_api = api_nb.NbApi.get_instance(False)
    service_instance = metadata_service.DFMetadataProxyHandler(
            cfg.CONF, nb_api)
    df_service.register_service(
            'df-metadata-service', nb_api, service_instance)
    service = wsgi.Server('dragonflow-metadata-service', disable_ssl=True)
    service.start(
        service_instance,
        host=cfg.CONF.df_metadata.ip,
        port=cfg.CONF.df_metadata.port,
    )
    service.wait()
    environment_destroy()
