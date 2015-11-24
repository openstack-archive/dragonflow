# Copyright 2015 Huawei Technologies Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg
from oslo_log import log as logging

from neutron.api.rpc.agentnotifiers import dhcp_rpc_agent_api
from neutron.common import topics

LOG = logging.getLogger(__name__)


class DFDhcpNotifyAPI(dhcp_rpc_agent_api.DhcpAgentNotifyAPI):
    """API for plugin to notify DHCP Chnages."""

    def __init__(self, topic=topics.DHCP_AGENT, plugin=None):
        super(DFDhcpNotifyAPI, self).__init__(topic, plugin)

    def network_removed_from_agent(self, context, network_id, host):
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            super(DFDhcpNotifyAPI, self).network_removed_from_agent(
                context,
                network_id,
                host)

    def network_added_to_agent(self, context, network_id, host):
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            super(DFDhcpNotifyAPI, self).network_added_to_agent(
                context,
                network_id,
                host)

    def agent_updated(self, context, admin_state_up, host):
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            super(DFDhcpNotifyAPI, self).agent_updated(
                context,
                admin_state_up,
                host)

    def notify(self, context, data, method_name):
        if cfg.CONF.df.use_centralized_ipv6_DHCP:
            super(DFDhcpNotifyAPI, self).notify(
                context,
                data,
                method_name)
