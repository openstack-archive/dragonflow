# Copyright (c) 2015 OpenStack Foundation.
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
#

from oslo_config import cfg

from dragonflow.controller import openflow_controller as of_controller
from dragonflow.neutron.agent.l3 import df_dvr_router

from neutron.agent.l3 import agent
from neutron.agent.l3 import namespaces
from neutron.agent import rpc as agent_rpc
from neutron.common import constants as l3_constants
from neutron.common import topics
from neutron.i18n import _LE, _LI
from neutron.openstack.common import loopingcall
from oslo_log import log as logging
EXTERNAL_DEV_PREFIX = namespaces.EXTERNAL_DEV_PREFIX

LOG = logging.getLogger(__name__)

NET_CONTROL_L3_OPTS = [
    cfg.StrOpt('net_controller_l3_southbound_protocol',
               default='OpenFlow',
               help=("Southbound protocol to connect the forwarding"
                     "element Currently supports only OpenFlow")),
    cfg.IntOpt('subnet_flows_idle_timeout',
               default=300,
               help=("The L3 VM to VM traffic (between networks) flows are "
                     "configured with this idle timeout (in seconds), "
                     "value of 0 means no timeout")),
    cfg.IntOpt('subnet_flows_hard_timeout',
               default=0,
               help=("The L3 VM to VM traffic (between networks) flows are "
                     "configured with this hard timeout (in seconds), "
                     "value of 0 means no timeout"))
]

cfg.CONF.register_opts(NET_CONTROL_L3_OPTS)


class L3ControllerAgent(agent.L3NATAgent):

    def __init__(self, host, conf=None):
        super(L3ControllerAgent, self).__init__(host, conf)

        self.use_ipv6 = False

        if cfg.CONF.net_controller_l3_southbound_protocol == "OpenFlow":
            # Open Flow Controller
            LOG.info(_LI("Using Southbound OpenFlow Protocol "))
            self.controller = of_controller.OpenFlowController(cfg, "openflow")
        elif cfg.CONF.net_controller_l3_southbound_protocol == "OVSDB":
            LOG.error(_LE("Southbound OVSDB Protocol not implemented yet"))
        elif cfg.CONF.net_controller_l3_southbound_protocol == "OP-FLEX":
            LOG.error(_LE("Southbound OP-FLEX Protocol not implemented yet"))

        # Initialize the controller application
        self.controller.initialize()

        # Sync all ports data from neutron to the L3 Agent
        self.sync_ports_on_startup()

        # Start the controller application
        self.controller.start()

    def sync_ports_on_startup(self):
        try:
            routers = self.plugin_rpc.get_routers(self.context)
        except Exception:
            LOG.error(_LE("Failed synchronizing routers due to RPC error"))
            return

        for router in routers:
            for interface in router.get('_interfaces', []):
                for subnet in interface['subnets']:
                    self.sync_subnet_port_data(subnet['id'])

    def _create_router(self, router_id, router):
        args = []
        kwargs = {
            'router_id': router_id,
            'router': router,
            'use_ipv6': self.use_ipv6,
            'agent_conf': self.conf,
            'interface_driver': self.driver,
            'controller': self.controller,
            'host': self.host,
            'agent': self,
        }
        return df_dvr_router.DfDvrRouter(*args, **kwargs)

    def _safe_router_removed(self, router_id):
        """Try to delete a router and return True if successful."""
        self.controller.delete_router(router_id)

        super(L3ControllerAgent, self)._safe_router_removed(router_id)

    def _process_router_if_compatible(self, router):

        self.controller.sync_router(router)
        for interface in router.get('_interfaces', ()):
            for subnet_info in interface['subnets']:
                self.sync_subnet_port_data(subnet_info['id'])
        super(L3ControllerAgent, self)._process_router_if_compatible(router)

    def sync_subnet_port_data(self, subnet_id):
        ports_data = self.plugin_rpc.get_ports_by_subnet(self.context,
            subnet_id)
        router_ports = []
        if ports_data:
            for port in ports_data:
                seg_id = port.get('segmentation_id')
                if (seg_id is None) or (seg_id == 0):
                    router_ports.append(port)
                self.controller.sync_port(port)

            if (seg_id is not None) and (seg_id != 0):
                for router_port in router_ports:
                    router_port['segmentation_id'] = seg_id
                    self.controller.sync_port(router_port)

    def add_arp_entry(self, context, payload):
        """Add arp entry into router namespace.  Called from RPC."""
        port = payload['arp_table']
        self.controller.sync_port(port)

    def del_arp_entry(self, context, payload):
        """Delete arp entry from router namespace.  Called from RPC."""
        port = payload['arp_table']
        self.controller.delete_port(port)


class L3ControllerAgentWithStateReport(L3ControllerAgent,
                                       agent.L3NATAgentWithStateReport):

    def __init__(self, host, conf=None):
        super(L3ControllerAgentWithStateReport, self).__init__(host=host,
                conf=conf)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        self.agent_state = {
            'binary': 'neutron-l3-controller-agent',
            'host': host,
            'topic': topics.L3_AGENT,
            'configurations': {
                'agent_mode': 'legacy',
                'use_namespaces': self.conf.use_namespaces,
                'router_id': self.conf.router_id,
                'handle_internal_only_routers':
                self.conf.handle_internal_only_routers,
                'external_network_bridge': self.conf.external_network_bridge,
                'gateway_external_network_id':
                self.conf.gateway_external_network_id,
                'interface_driver': self.conf.interface_driver},
            'start_flag': True,
            'agent_type': l3_constants.AGENT_TYPE_L3}
        report_interval = self.conf.AGENT.report_interval
        self.use_call = True
        if report_interval:
            self.heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            self.heartbeat.start(interval=report_interval)
