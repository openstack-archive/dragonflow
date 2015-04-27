# Copyright (c) 2015 OpenStack Foundation.
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
from ryu.base.app_manager import AppManager
from ryu.controller.ofp_handler import OFPHandler


from neutron import context

from dragonflow.controller.base_controller import ControllerBase
from neutron.common import utils


from oslo_log import log as logging

from dragonflow.controller.l3_openflow_app import L3ReactiveApp
LOG = logging.getLogger(__name__)


class OpenFlowController(ControllerBase):

    def __init__(self, conf, controllertype):
        super(OpenFlowController, self).__init__(conf, controllertype)
        self.cfg = conf
        self.controllertype = controllertype
        self.ctx = context.get_admin_context()
        self.hostname = utils.get_hostname()
        self.sync_active_state = False
        self.sync_all = True
        self.l3_app = None
        self.heartbeat = None
        self.open_flow_hand = None
        self.start()

    def start(self):
        app_mgr = AppManager.get_instance()
        LOG.debug(("RYU openflow stack, DragonFlow OpenFlow Controller"))
        l3app_kwargs = dict(
            idle_timeout=self.cfg.CONF.subnet_flows_idle_timeout,
            hard_timeout=self.cfg.CONF.subnet_flows_hard_timeout
        )
        self.open_flow_hand = app_mgr.instantiate(OFPHandler, None, None)
        self.open_flow_hand.start()
        self.l3_app = app_mgr.instantiate(L3ReactiveApp, None, **l3app_kwargs)
        self.l3_app.start()

    def delete_router(self, router_id):
        self.l3_app.delete_router(router_id)

    def sync_router(self, router):
        self.l3_app.sync_router(router)

    def sync_port(self, port):
        self.l3_app.sync_port(port)

    def add_snat_binding(self, subnet_id, sn_port):
        self.l3_app.add_snat_binding(subnet_id, sn_port)

    def remove_snat_binding(self, subnet_id):
        self.l3_app.remove_snat_binding(subnet_id)
