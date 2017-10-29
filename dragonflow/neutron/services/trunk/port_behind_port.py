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

import netaddr
from neutron_lib.api.definitions import allowedaddresspairs as aap
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as n_constants
from neutron_lib import context
from neutron_lib.plugins import directory
from oslo_log import log

from dragonflow.db.models import trunk as trunk_models
from dragonflow.neutron.services import mixins


LOG = log.getLogger(__name__)


@registry.has_registry_receivers
class DfPortBehindPortDetector(mixins.LazyNbApiMixin):

    def _get_child_port_status(self, parent_port):
        new_status = n_constants.PORT_STATUS_ACTIVE
        if parent_port['status'] != n_constants.PORT_STATUS_ACTIVE:
            new_status = n_constants.PORT_STATUS_DOWN
        return new_status

    def _detect_macvlan(self, a_context, updated_port, orig_port=None):
        """
        A heuristic to detect MACVLAN ports (i.e. ports behind ports).
        For each allowed-address-pair modification, scan to see if there are
        ports with those IPs/MACs. If so, these are MACVLAN ports, and create
        the relevant NB objects
        """
        # TODO(oanson) We assume that the AAP is removed before the port
        updated_port_aaps = updated_port.get(aap.ADDRESS_PAIRS, [])
        orig_port_aaps = ([] if not orig_port else
                          orig_port.get(aap.ADDRESS_PAIRS, []))
        new_aaps = [e for e in updated_port_aaps if e not in orig_port_aaps]
        removed_aaps = [e for e in orig_port_aaps
                        if e not in updated_port_aaps]
        core_plugin = directory.get_plugin()
        new_status = self._get_child_port_status(updated_port)
        LOG.debug('_detect_macvlan: id: %s '
                  'updated_port_aaps: %s orig_port_aaps: %s',
                  updated_port['id'], updated_port_aaps, orig_port_aaps)

        for pair in new_aaps:
            macvlan_port, segmentation_type = self._find_macvlan_port(
                a_context, pair, updated_port)
            if not macvlan_port:
                LOG.debug('_detect_macvlan (new): '
                          'Could not find port with ip pair %s', pair)
                continue
            cps_id = trunk_models.get_child_port_segmentation_id(
                    updated_port['id'], macvlan_port['id'])
            model = trunk_models.ChildPortSegmentation(
                id=cps_id,
                topic=updated_port['project_id'],
                parent=updated_port['id'],
                port=macvlan_port['id'],
                segmentation_type=segmentation_type,
            )
            self.nb_api.create(model)
            core_plugin.update_port_status(context.get_admin_context(),
                                           macvlan_port['id'], new_status)

        for pair in removed_aaps:
            macvlan_port, _segmentation_type = self._find_macvlan_port(
                a_context, pair, updated_port)
            if not macvlan_port:
                LOG.debug('_detect_macvlan (removed): '
                          'Could not find port with ip pair %s', pair)
                continue
            cps_id = trunk_models.get_child_port_segmentation_id(
                    updated_port['id'], macvlan_port['id'])
            model = trunk_models.ChildPortSegmentation(
                id=cps_id,
                topic=updated_port['project_id'],
            )
            self.nb_api.delete(model)
            core_plugin.update_port_status(context.get_admin_context(),
                                           macvlan_port['id'],
                                           n_constants.PORT_STATUS_DOWN)

    def _find_macvlan_port(self, context, pair, port):
        try:
            ip = netaddr.IPAddress(pair['ip_address'])
        except ValueError:
            return None  # Skip. This is a network, not a host
        mac_address = pair.get('mac_address')
        if mac_address and mac_address == port['mac_address']:
            mac_address = None
        if ip is None and mac_address is None:
            return None
        filters = {}
        if ip:
            filters['fixed_ips'] = {'ip_address': [str(ip)]}
        if mac_address:
            filters['mac_address'] = [str(mac_address)]
        core_plugin = directory.get_plugin()
        ports = core_plugin.get_ports(context, filters=filters)
        if ports:
            segmentation_type = (trunk_models.TYPE_MACVLAN if mac_address
                                 else trunk_models.TYPE_IPVLAN)
            return ports[0], segmentation_type
        return None

    @registry.receives(resources.PORT,
                       [events.AFTER_CREATE, events.AFTER_UPDATE])
    def _update_port_aap_handler(self, *args, **kwargs):
        port = kwargs['port']
        orig_port = kwargs.get('original_port')
        self._detect_macvlan(kwargs['context'], port, orig_port)
