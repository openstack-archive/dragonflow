# Copyright (c) 2015 OpenStack Foundation.
#
# All Rights Reserved.
#
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
import sys
eventlet.monkey_patch()

from oslo_config import cfg

from neutron.agent.common import config
from neutron.agent import l3_agent
from neutron.common import config as common_config
from neutron.common import topics
from neutron.openstack.common import service
from neutron import service as neutron_service


def main(manager='dragonflow.neutron.agent.l3.l3_controller_agent.'
         'L3ControllerAgentWithStateReport'):
    l3_agent.register_opts(cfg.CONF)
    common_config.init(sys.argv[1:])
    config.setup_logging()
    cfg.CONF.set_override('router_delete_namespaces', True)
    server = neutron_service.Service.create(
        binary='neutron-l3-controller-agent',
        topic=topics.L3_AGENT,
        report_interval=cfg.CONF.AGENT.report_interval,
        manager=manager)
    service.launch(server).wait()

if __name__ == "__main__":
    main()
