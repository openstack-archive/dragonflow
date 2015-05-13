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

from neutron.agent.l3 import legacy_router
from neutron.i18n import _LE

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class DfDvrRouter(legacy_router.LegacyRouter):

    def __init__(self, agent, host, controller, *args, **kwargs):
        super(DfDvrRouter, self).__init__(*args, **kwargs)
        self.agent = agent
        self.host = host
        self.controller = controller

    def _add_snat_binding_to_controller(self, sn_port):
        if sn_port is None:
            return

        LOG.debug("_add_snat_binding_to_controller")
        LOG.debug("subnet = %s" % sn_port['fixed_ips'][0]['subnet_id'])
        LOG.debug("ip = %s" % sn_port['fixed_ips'][0]['ip_address'])
        LOG.debug("mac = %s" % sn_port['mac_address'])

        self.controller.add_snat_binding(
            sn_port['fixed_ips'][0]['subnet_id'], sn_port)

    def _remove_snat_binding_to_controller(self, sn_port):
        if sn_port is None:
            LOG.error(_LE("None sn_port"))
            return

        LOG.debug("_remove_snat_binding_to_controller")
        LOG.debug("subnet = %s" % sn_port['fixed_ips'][0]['subnet_id'])
        LOG.debug("ip = %s" % sn_port['fixed_ips'][0]['ip_address'])
        LOG.debug("mac = %s" % sn_port['mac_address'])

        self.controller.remove_snat_binding(
            sn_port['fixed_ips'][0]['subnet_id'])

    def internal_network_added(self, port):
        super(DfDvrRouter, self).internal_network_added(port)

        if self.router.get('enable_snat'):
            self._add_snat_binding_to_controller(port)

    def internal_network_removed(self, port):
        super(DfDvrRouter, self).internal_network_removed(port)

        if self.router.get('enable_snat'):
            self._remove_snat_binding_to_controller(port)

    def external_gateway_added(self, ex_gw_port, interface_name):
        super(DfDvrRouter, self).external_gateway_added(
            ex_gw_port, interface_name)

        for p in self.internal_ports:
            self._add_snat_binding_to_controller(p)

    def external_gateway_updated(self, ex_gw_port, interface_name):
        super(DfDvrRouter, self).external_gateway_updated(
            ex_gw_port, interface_name)

    def external_gateway_removed(self, ex_gw_port, interface_name):
        super(DfDvrRouter, self).external_gateway_removed(
            ex_gw_port, interface_name)

        for p in self.internal_ports:
            self._remove_snat_binding_to_controller(p)

    def routes_updated(self):
        pass
