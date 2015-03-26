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

from neutron.agent.l3 import dvr_router
from neutron.agent.l3 import dvr_snat_ns
from neutron.agent.l3 import router_info as router
from neutron.agent.linux import ip_lib
from neutron.common import constants as l3_constants

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class DfDvrRouter(dvr_router.DvrRouter):

    def __init__(self, agent, host, *args, **kwargs):
        super(DfDvrRouter, self).__init__(agent, host, *args, **kwargs)

    def _process_internal_ports(self):
        existing_port_ids = set(p['id'] for p in self.internal_ports)

        internal_ports = self.router.get(l3_constants.INTERFACE_KEY, [])
        current_port_ids = set(p['id'] for p in internal_ports
                               if p['admin_state_up'])

        new_port_ids = current_port_ids - existing_port_ids
        new_ports = [p for p in internal_ports if p['id'] in new_port_ids]
        old_ports = [p for p in self.internal_ports
                     if p['id'] not in current_port_ids]

        for p in new_ports:
            self._set_subnet_info(p)
            self.internal_network_added(p)
            self.internal_ports.append(p)

        for p in old_ports:
            self.internal_network_removed(p)
            self.internal_ports.remove(p)

    def internal_network_added(self, port):
        ex_gw_port = self.get_ex_gw_port()
        if not ex_gw_port:
            return

        snat_ports = self.get_snat_interfaces()
        sn_port = self._map_internal_interfaces(port, snat_ports)
        if not sn_port:
            return

        # This needs to set the correct flows in the SDN app
        interface_name = self.get_internal_device_name(port['id'])
        # self._snat_redirect_add(sn_port['fixed_ips'][0]['ip_address'],
        #                         port,
        #                         interface_name)

        if not self._is_this_snat_host():
            return

        # LOG.error("internal_network_added")
        # LOG.error("subnet = " + sn_port['fixed_ips'][0]['subnet_id'])
        # LOG.error("ip = " + sn_port['fixed_ips'][0]['ip_address'])
        # LOG.error("mac = " + sn_port['mac_address'])

        ns_name = dvr_snat_ns.SnatNamespace.get_snat_ns_name(self.router['id'])
        self._set_subnet_info(sn_port)
        interface_name = self.get_snat_int_device_name(sn_port['id'])
        self._internal_network_added(
            ns_name,
            sn_port['network_id'],
            sn_port['id'],
            sn_port['ip_cidr'],
            sn_port['mac_address'],
            interface_name,
            dvr_snat_ns.SNAT_INT_DEV_PREFIX)

        #self._set_subnet_arp_info(port)

    def internal_network_removed(self, port):
        if not self.ex_gw_port:
            return

        sn_port = self._map_internal_interfaces(port, self.snat_ports)
        if not sn_port:
            return

        # This needs to remove the correct flows in the SDN app
        # interface_name = self.get_internal_device_name(port['id'])
        # self._snat_redirect_remove(sn_port['fixed_ips'][0]['ip_address'],
        #                            port,
        #                            interface_name)

        mode = self.agent_conf.agent_mode
        is_this_snat_host = (mode == l3_constants.L3_AGENT_MODE_DVR_SNAT
            and self.ex_gw_port['binding:host_id'] == self.host)
        if not is_this_snat_host:
            return

        snat_interface = (
            self.get_snat_int_device_name(sn_port['id']))
        ns_name = self.snat_namespace.name
        prefix = dvr_snat_ns.SNAT_INT_DEV_PREFIX
        if ip_lib.device_exists(snat_interface, namespace=ns_name):
            self.driver.unplug(snat_interface, namespace=ns_name,
                               prefix=prefix)

    def process_external(self, agent):
        ex_gw_port = self.get_ex_gw_port()
        self._process_external_gateway(ex_gw_port)

    def _process_external_gateway(self, ex_gw_port):
        ex_gw_port_id = (ex_gw_port and ex_gw_port['id'] or
                         self.ex_gw_port and self.ex_gw_port['id'])

        interface_name = None
        if ex_gw_port_id:
            interface_name = self.get_external_device_name(ex_gw_port_id)
        if ex_gw_port:
            def _gateway_ports_equal(port1, port2):
                def _get_filtered_dict(d, ignore):
                    return dict((k, v) for k, v in d.iteritems()
                                if k not in ignore)

                keys_to_ignore = set(['binding:host_id'])
                port1_filtered = _get_filtered_dict(port1, keys_to_ignore)
                port2_filtered = _get_filtered_dict(port2, keys_to_ignore)
                return port1_filtered == port2_filtered

            self._set_subnet_info(ex_gw_port)
            if not self.ex_gw_port:
                self.external_gateway_added(ex_gw_port, interface_name)
            elif not _gateway_ports_equal(ex_gw_port, self.ex_gw_port):
                self.external_gateway_updated(ex_gw_port, interface_name)
        elif not ex_gw_port and self.ex_gw_port:
            self.external_gateway_removed(self.ex_gw_port, interface_name)

        # Process SNAT rules for external gateway
        self.perform_snat_action(self._handle_router_snat_rules,
                                 interface_name)

    def external_gateway_added(self, ex_gw_port, interface_name):
        snat_ports = self.get_snat_interfaces()
        # for p in self.internal_ports:
        #     gateway = self._map_internal_interfaces(p, snat_ports)
        #     id_name = self.get_internal_device_name(p['id'])
        #     if gateway:
        #         self._snat_redirect_add(
        #             gateway['fixed_ips'][0]['ip_address'], p, id_name)

        if self._is_this_snat_host():
            self._create_dvr_gateway(ex_gw_port, interface_name, snat_ports)

        # for port in snat_ports:
        #     for ip in port['fixed_ips']:
        #         self._update_arp_entry(ip['ip_address'],
        #                                port['mac_address'],
        #                                ip['subnet_id'],
        #                                'add')

    def external_gateway_updated(self, ex_gw_port, interface_name):
        if not self._is_this_snat_host():
            # no centralized SNAT gateway for this node/agent
            LOG.debug("not hosting snat for router: %s", self.router['id'])
            return

        self._external_gateway_added(ex_gw_port,
                                     interface_name,
                                     self.snat_namespace.name,
                                     preserve_ips=[])

    def external_gateway_removed(self, ex_gw_port, interface_name):
        # snat_ports = self.get_snat_interfaces()
        # for p in self.internal_ports:
        #     gateway = self._map_internal_interfaces(p, snat_ports)
        #     internal_interface = self.get_internal_device_name(p['id'])
        #     self._snat_redirect_remove(gateway['fixed_ips'][0]['ip_address'],
        #                                p,
        #                                internal_interface)

        if not self._is_this_snat_host():
            # no centralized SNAT gateway for this node/agent
            LOG.debug("not hosting snat for router: %s", self.router['id'])
            return

        self.driver.unplug(interface_name,
                           bridge=self.agent_conf.external_network_bridge,
                           namespace=self.snat_namespace.name,
                           prefix=router.EXTERNAL_DEV_PREFIX)

        self.snat_namespace.delete()
        self.snat_namespace = None

    def _is_this_snat_host(self):
        mode = self.agent_conf.agent_mode
        return (mode == l3_constants.L3_AGENT_MODE_DVR_SNAT
                and self.get_gw_port_host() == self.host)
