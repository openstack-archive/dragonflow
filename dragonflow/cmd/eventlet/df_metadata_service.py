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

from dragonflow._i18n import _LI
from dragonflow import conf as cfg
from dragonflow.controller import metadata_service_app

import sys


LOG = log.getLogger(__name__)

METADATA_ROUTE_TABLE_ID = '2'


def environment_setup():
    bridge = cfg.CONF.df.integration_bridge
    interface = cfg.CONF.df.metadata_interface
    if ip_lib.device_exists(interface):
        LOG.info(_LI("Device %s already exists"), interface)
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


def environment_destroy():
    bridge = cfg.CONF.df.integration_bridge
    interface = cfg.CONF.df.metadata_interface
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
    service = wsgi.Server('dragonflow-metadata-service', disable_ssl=True)
    service.start(
        metadata_service_app.DFMetadataProxyHandler(cfg.CONF),
        host=cfg.CONF.df_metadata.ip,
        port=cfg.CONF.df_metadata.port,
    )
    service.wait()
    environment_destroy()
