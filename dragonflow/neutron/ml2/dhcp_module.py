# Copyright (c) 2017 Huawei Tech. Co., Ltd. .
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

from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as n_const
from neutron_lib.plugins import directory
from oslo_log import log

LOG = log.getLogger(__name__)


def _is_subnet_enable_dhcp(subnet):
    return subnet['enable_dhcp'] is True


def _is_dhcp_port(port):
    return port['device_owner'] == n_const.DEVICE_OWNER_DHCP


class DfDHCPMoudle(object):

    def __init__(self):
        self._register_subnet_events()

    @property
    def core_plugin(self):
        return directory.get_plugin()

    def _register_events(self, resource, function_by_action):
        for action, func in function_by_action.items():
            registry.subscribe(func, resource, action)

    def _register_subnet_events(self):
        function_by_action = {
            events.AFTER_CREATE: self._subnet_create_handler,
            events.AFTER_UPDATE: self._subnet_update_handler,
            events.AFTER_DELETE: self._sunet_delete_handler
        }
        self._register_events(resources.SUBNET, function_by_action)

    def _get_lswitch_dhcp_port(self, network_id, context):
        filters = {'device_owner': [n_const.DEVICE_OWNER_DHCP]}
        ports = self.core_plugin.get_ports(context, filters=filters)

        if 0 != len(ports):
            for port in ports:
                if network_id == ports[0]['network_id']:
                    return port
        else:
            return None

    def _create_dhcp_port(self, context, subnet):
        port = {'port': {'tenant_id': subnet['tenant_id'],
                         'network_id': subnet['network_id'], 'name': '',
                         'admin_state_up': True, 'device_id': '',
                         'device_owner': n_const.DEVICE_OWNER_DHCP,
                         'mac_address': n_const.ATTR_NOT_SPECIFIED,
                         'fixed_ips': [{'subnet_id': subnet['id']}]}}
        self.core_plugin.create_port(context, port)

    def _update_dhcp_port(self, context, port, subnet):
        fixed_ips = port['fixed_ips']
        fixed_ips.append({'subnet_id': subnet['id']})
        self.core_plugin.update_port(context, port['id'], {'port': port})

    def _add_dhcp_subnet_to_network(self, context, network, subnet):
        port = self._get_lswitch_dhcp_port(network, context)
        if port is not None:
            self._update_dhcp_port(context, port, subnet)
        else:
            self._create_dhcp_port(context, subnet)

    def _remove_dhcp_subnet_from_network(self, context, network_id, subnet):
        port = self._get_lswitch_dhcp_port(network_id, context)
        if not port:
            return

        fixed_ips = port['fixed_ips']
        port['fixed_ips'] = [x for x in
                             fixed_ips if
                             x['subnet_id'] != subnet['id']]

        if len(port['fixed_ips']) == 0:
            # No subnet that enabled DHCP on the port any more
            self.core_plugin.delete_port(context, port)
        else:
            self.core_plugin.update_port(context, port['id'], {'port': port})

    def _subnet_create_handler(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        subnet = kwargs['subnet']
        if not _is_subnet_enable_dhcp(subnet):
            return
        self._add_dhcp_subnet_to_network(context, subnet['network_id'],
                                         subnet)

    def _is_dhcp_state_change(self, orig_subnet, subnet):
        if (_is_subnet_enable_dhcp(subnet) !=
                _is_subnet_enable_dhcp(orig_subnet)):
            return True
        if orig_subnet['network_id'] != subnet['network_id']:
            return True
        return False

    def _subnet_update_handler(self, resource, event, trigger, **kwargs):
        subnet = kwargs['subnet']
        context = kwargs['context']
        orig_subnet = kwargs['original_subnet']
        if self._is_dhcp_state_change(orig_subnet, subnet):
            if _is_subnet_enable_dhcp(orig_subnet):
                self._remove_dhcp_subnet_from_network(context,
                                                      subnet['network_id'],
                                                      subnet)
            if _is_subnet_enable_dhcp(subnet):
                self._add_dhcp_subnet_to_network(subnet['network_id'], subnet)

    def _sunet_delete_handler(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        subnet = kwargs['subnet']

        if _is_subnet_enable_dhcp(subnet):
            self._remove_dhcp_subnet_from_network(context,
                                                  subnet['network_id'],
                                                  subnet)
