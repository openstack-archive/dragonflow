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

import eventlet
from oslo_config import cfg
import oslo_messaging
from oslo_utils import excutils
from oslo_utils import timeutils

from dragonflow.controller import openflow_controller as of_controller
#from neutron.agent.common import config
from neutron.agent.l3 import agent
from neutron.agent.l3 import router_processing_queue as queue
from neutron.agent import rpc as agent_rpc
from neutron.common import constants as l3_constants
from neutron.common import topics
from neutron.common import utils as common_utils
from neutron import context as n_context
from neutron.i18n import _LE, _LI, _LW
from neutron import manager
from neutron.openstack.common import loopingcall
from neutron.openstack.common import periodic_task
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

NET_CONTROL_L3_OPTS = [
    cfg.StrOpt('L3controller_ip_list',
               default='tcp:172.16.10.10:6633',
               help=("L3 Controler IP list list tcp:ip_addr:port;"
                     "tcp:ip_addr:port..;..")),
    cfg.StrOpt('net_controller_l3_southbound_protocol',
               default='OpenFlow',
               help=("Southbound protocol to connect the forwarding"
                     "element Currently supports only OpenFlow"))
]

cfg.CONF.register_opts(NET_CONTROL_L3_OPTS)


class L3ControllerAgent(manager.Manager):
    """Manager for L3ControllerAgent

        API version history:
        1.0 initial Version
        1.1 changed the type of the routers parameter
            to the routers_updated method.
            It was previously a list of routers in dict format.
            It is now a list of router IDs only.
            Per rpc versioning rules,  it is backwards compatible.
        1.2 - DVR support: new L3 agent methods added.
              - add_arp_entry
              - del_arp_entry
              Needed by the L3 service when dealing with DVR
    """
    target = oslo_messaging.Target(version='1.2')

    def __init__(self, host, conf=None):
        if conf:
            self.conf = conf
        else:
            self.conf = cfg.CONF
        self.router_info = {}

        self._check_config_params()
        self.context = n_context.get_admin_context_without_session()
        self.plugin_rpc = agent.L3PluginApi(topics.L3PLUGIN, host)
        self.fullsync = True

        # Get the list of service plugins from Neutron Server
        # This is the first place where we contact neutron-server on startup
        # so retry in case its not ready to respond.
        retry_count = 5
        while True:
            retry_count = retry_count - 1
            try:
                self.neutron_service_plugins = (
                    self.plugin_rpc.get_service_plugin_list(self.context))
            except oslo_messaging.RemoteError as e:
                with excutils.save_and_reraise_exception() as ctx:
                    ctx.reraise = False
                    LOG.warning(_LW('l3-agent cannot check service plugins '
                                    'enabled at the neutron server when '
                                    'startup due to RPC error. It happens '
                                    'when the server does not support this '
                                    'RPC API. If the error is '
                                    'UnsupportedVersion you can ignore this '
                                    'warning. Detail message: %s'), e)
                self.neutron_service_plugins = None
            except oslo_messaging.MessagingTimeout as e:
                with excutils.save_and_reraise_exception() as ctx:
                    if retry_count > 0:
                        ctx.reraise = False
                        LOG.warning(_LW('l3-agent cannot check service '
                                        'plugins enabled on the neutron '
                                        'server. Retrying. '
                                        'Detail message: %s'), e)
                        continue
            break

        if cfg.CONF.net_controller_l3_southbound_protocol == "OpenFlow":
            # Open Flow Controller
            LOG.info(_LI("Using Southbound OpenFlow Protocol "))
            self.controller = of_controller.OpenFlowController(cfg, "openflow")

        elif cfg.CONF.net_controller_l3_southbound_protocol == "OVSDB":
            LOG.error(_LE("Southbound OVSDB Protocol not implemented yet"))
        elif cfg.CONF.net_controller_l3_southbound_protocol == "OP-FLEX":
            LOG.error(_LE("Southbound OP-FLEX Protocol not implemented yet"))
        self._queue = queue.RouterProcessingQueue()
        #self.event_observers = event_observers.L3EventObservers()
        super(L3ControllerAgent, self).__init__()

    def _check_config_params(self):
        """Check items in configuration files.

        Check for required and invalid configuration items.
        The actual values are not verified for correctness.
        """

    @common_utils.exception_logger()
    def process_router(self, ri):
        # TODO(mrsmith) - we shouldn't need to check here
        if 'distributed' not in ri.router:
            ri.router['distributed'] = False
        ex_gw_port = self._get_ex_gw_port(ri)
        if ri.router.get('distributed') and ex_gw_port:
            ri.fip_ns = self.get_fip_ns(ex_gw_port['network_id'])
            ri.fip_ns.scan_fip_ports(ri)
        self._process_internal_ports(ri)
        self._process_external(ri)
        # Process static routes for router
        ri.routes_updated()

        # Enable or disable keepalived for ha routers
        self._process_ha_router(ri)

        # Update ex_gw_port and enable_snat on the router info cache
        ri.ex_gw_port = ex_gw_port
        ri.snat_ports = ri.router.get(l3_constants.SNAT_ROUTER_INTF_KEY, [])
        ri.enable_snat = ri.router.get('enable_snat')

    def router_deleted(self, context, router_id):
        """Deal with router deletion RPC message."""
        LOG.debug('Got router deleted notification for %s', router_id)
        update = queue.RouterUpdate(router_id,
                                    queue.PRIORITY_RPC,
                                    action=queue.DELETE_ROUTER)
        self._queue.add(update)

    def routers_updated(self, context, routers):
        """Deal with routers modification and creation RPC message."""
        LOG.debug('Got routers updated notification :%s', routers)
        if routers:
            # This is needed for backward compatibility
            if isinstance(routers[0], dict):
                routers = [router['id'] for router in routers]
            for id in routers:
                update = queue.RouterUpdate(id, queue.PRIORITY_RPC)
                self._queue.add(update)

    def router_removed_from_agent(self, context, payload):
        LOG.debug('Got router removed from agent :%r', payload)
        router_id = payload['router_id']
        update = queue.RouterUpdate(router_id,
                                    queue.PRIORITY_RPC,
                                    action=queue.DELETE_ROUTER)
        self._queue.add(update)

    def router_added_to_agent(self, context, payload):
        LOG.debug('Got router added to agent :%r', payload)
        self.routers_updated(context, payload)

    def _process_router_updates(self):
        for (
            router_processor, update
        ) in self._queue.each_update_to_next_router():
            self._process_router_update(router_processor, update)

    def _process_router_update(self, router_processor, update):
        LOG.debug("Starting router update for %s", update.id)

        router = update.router
        if update.action != queue.DELETE_ROUTER and not router:
            try:
                update.timestamp = timeutils.utcnow()
                routers = self.plugin_rpc.get_routers(self.context,
                                                      [update.id])
            except Exception:
                msg = _LE("Failed to fetch router information for '%s'")
                LOG.exception(msg, update.id)
                self.fullsync = True
                return

            if routers:
                router = routers[0]

        if not router:
            self.controller.delete_router(update.id)
            return

        #self._process_router_if_compatible(router)
        self.controller.sync_router(router)

        for interface in router.get('_interfaces', ()):
            self.sync_subnet_port_data(interface['subnet']['id'])

        LOG.debug("Finished a router update for %s", update.id)
        router_processor.fetched_and_processed(update.timestamp)

    def _process_routers_loop(self):
        LOG.debug("Starting _process_routers_loop")
        pool = eventlet.GreenPool(size=8)
        while True:
            pool.spawn_n(self._process_router_updates)

    def sync_subnet_port_data(self, subnet_id):
        ports_data = self.plugin_rpc.get_ports_by_subnet(self.context,
            subnet_id)
        if ports_data:
            for port in ports_data:
                self.controller.sync_port(port)

    @periodic_task.periodic_task
    def periodic_sync_routers_task(self, context):
        #if self.services_sync:
        LOG.debug("Starting periodic_sync_routers_task - fullsync:%s",
                  self.fullsync)
        if not self.fullsync:
            return
        # self.fullsync is True at this point. If an exception -- caught or
        # uncaught -- prevents setting it to False below then the next call
        # to periodic_sync_routers_task will re-enter this code and try again.

        # Capture a picture of namespaces *before* fetching the full list from
        # the database.  This is important to correctly identify stale ones.
        prev_router_ids = set(self.router_info)
        timestamp = timeutils.utcnow()

        try:
                routers = self.plugin_rpc.get_routers(context)

        except oslo_messaging.MessagingException:
            LOG.exception(_LE("Failed synchronizing routers due to RPC error"))
        else:
            LOG.debug('Processing :%r', routers)
            for r in routers:
                update = queue.RouterUpdate(r['id'],
                                            queue.PRIORITY_SYNC_ROUTERS_TASK,
                                            router=r,
                                            timestamp=timestamp)
                self._queue.add(update)
            #if self.fullsync:

            self.fullsync = False
            LOG.debug("periodic_sync_routers_task successfully completed")

            curr_router_ids = set([r['id'] for r in routers])

            # Two kinds of stale routers:  Routers for which info is cached in
            # self.router_info and the others.  First, handle the former.
            for router_id in prev_router_ids - curr_router_ids:
                update = queue.RouterUpdate(router_id,
                                            queue.PRIORITY_SYNC_ROUTERS_TASK,
                                            timestamp=timestamp,
                                            action=queue.DELETE_ROUTER)
                self._queue.add(update)

    def after_start(self):
        eventlet.spawn_n(self._process_routers_loop)
        LOG.info(_LI("L3 agent started"))
        # When L3 agent is ready, we immediately do a full sync
        self.periodic_sync_routers_task(self.context)

    def add_arp_entry(self, context, payload):
        """Add arp entry into router namespace.  Called from RPC."""
        port = payload['arp_table']
        self.controller.sync_port(port)

    def del_arp_entry(self, context, payload):
        """Delete arp entry from router namespace.  Called from RPC."""
        #arp_table = payload['arp_table']
        # TODO(gampel) FIX add call to controller to delte entry
        LOG.debug("NOT IMP YET del_arp_entry")


class L3ControllerAgentWithStateReport(L3ControllerAgent):

    def __init__(self, host, conf=None):
        super(L3ControllerAgentWithStateReport, self).__init__(host=host,
                conf=conf)
        self.state_rpc = agent_rpc.PluginReportStateAPI(topics.PLUGIN)
        self.agent_state = {
            'binary': 'neutron-l3-controller-agent',
            'host': host,
            'topic': topics.L3_AGENT,
            'configurations': {
                #'agent_mode': self.conf.agent_mode,
                'agent_mode': "dvr_snat",
                'router_id': self.conf.router_id,
                'handle_internal_only_routers':
                self.conf.handle_internal_only_routers,
                'external_network_bridge': self.conf.external_network_bridge,
                'gateway_external_network_id':
                self.conf.gateway_external_network_id},
            'start_flag': True,
            'agent_type': l3_constants.AGENT_TYPE_L3}
        report_interval = self.conf.AGENT.report_interval
        self.use_call = True
        if report_interval:
            self.heartbeat = loopingcall.FixedIntervalLoopingCall(
                self._report_state)
            self.heartbeat.start(interval=report_interval)

    def _report_state(self):
        LOG.debug("Report state task started")
        num_ex_gw_ports = 0
        num_interfaces = 0
        num_floating_ips = 0
        num_routers = 2
#        router_infos = self.router_info.values()
#        num_routers = len(router_infos)
#        for ri in router_infos:
#            ex_gw_port = self._get_ex_gw_port(ri)
#            if ex_gw_port:
#                num_ex_gw_ports += 1
#            num_interfaces += len(ri.router.get(l3_constants.INTERFACE_KEY,
#                                                []))
#            num_floating_ips += len(ri.router.get(l3_constants.FLOATINGIP_KEY,
#                                                  []))
        configurations = self.agent_state['configurations']
        configurations['routers'] = num_routers
        configurations['ex_gw_ports'] = num_ex_gw_ports
        configurations['interfaces'] = num_interfaces
        configurations['floating_ips'] = num_floating_ips
        try:
            self.state_rpc.report_state(self.context, self.agent_state,
                                        self.use_call)
            self.agent_state.pop('start_flag', None)
            self.use_call = False
            LOG.debug("Report state task successfully completed")
        except AttributeError:
            # This means the server does not support report_state
            LOG.warn(_LW("Neutron server does not support state report."
                         " State report for this agent will be disabled."))
            self.heartbeat.stop()
            return
        except Exception:
            LOG.exception(_LE("Failed reporting state!"))

    def agent_updated(self, context, payload):
        """Handle the agent_updated notification event."""
        self.fullsync = True
        LOG.info(_LI("agent_updated by server side %s!"), payload)
