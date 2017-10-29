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

import uuid

import netaddr
from neutron.services.trunk import constants
from neutron.services.trunk.drivers import base
from neutron_lib.api.definitions import allowedaddresspairs as aap
from neutron_lib.api.definitions import portbindings
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as n_constants
from neutron_lib import context
from neutron_lib.plugins import directory
from oslo_log import log

from dragonflow import conf as cfg
from dragonflow.db.models import l2
from dragonflow.db.models import trunk as trunk_models
from dragonflow.neutron.services import mixins


LOG = log.getLogger(__name__)


class DfTrunkDriver(base.DriverBase, mixins.LazyNbApiMixin):
    def __init__(self):
        super(DfTrunkDriver, self).__init__(
            'df',
            (portbindings.VIF_TYPE_OVS, portbindings.VIF_TYPE_VHOST_USER),
            (constants.VLAN,),
            can_trunk_bound_port=True
        )
        self._nb_api = None
        self._register_init_events()

    @property
    def is_loaded(self):
        try:
            # TODO(oanson) 'df' -> constant
            return 'df' in cfg.CONF.ml2.mechanism_drivers
        except cfg.NoSuchOptError:
            return False

    def register(self, resource, event, trigger, payload=None):
        """
        Register the Dragonflow driver. This means registering to the
        add subport and delete subport events
        """
        super(DfTrunkDriver, self).register(resource, event, trigger,
                                            payload=payload)
        self._register_trunk_events()
        self._register_subport_events()

    def _register_init_events(self):
        registry.subscribe(self.register,
                           constants.TRUNK_PLUGIN,
                           events.AFTER_INIT)
        registry.subscribe(self._update_port_aap_handler,
                           resources.PORT, events.AFTER_UPDATE)
        registry.subscribe(self._create_port_aap_handler,
                           resources.PORT, events.AFTER_CREATE)

    def _register_trunk_events(self):
        registry.subscribe(self._add_trunk_handler,
                           constants.TRUNK, events.AFTER_CREATE)

    def _register_subport_events(self):
        registry.subscribe(self._add_subports_handler,
                           constants.SUBPORTS, events.AFTER_CREATE)
        registry.subscribe(self._delete_subports_handler,
                           constants.SUBPORTS, events.AFTER_DELETE)
        registry.subscribe(self._update_port_handler,
                           resources.PORT, events.AFTER_UPDATE)

    def _get_subport_id(self, trunk, subport):
        """
        Generate a repeatable uuid, so we can identify the Dragonflow
        ChildPortSegmentation object
        """
        base = "{}/{}".format(trunk.port_id, subport.port_id)
        return str(uuid.uuid5(trunk_models.UUID_NAMESPACE, base))

    def _add_trunk_handler(self, *args, **kwargs):
        """Handle the event that trunk was created"""
        payload = kwargs['payload']
        trunk = payload.current_trunk
        trunk.update(status=constants.ACTIVE_STATUS)

    def _add_subports_handler(self, *args, **kwargs):
        """Handle the event that subports were created"""
        payload = kwargs['payload']
        trunk = payload.current_trunk
        subports = payload.subports
        self._add_subports(trunk, subports)

    def _add_subports(self, trunk, subports):
        """
        Create the subports that were created on the Neutron side in the
        Dragonflow NB DB
        """
        df_parent = self.nb_api.get(l2.LogicalPort(id=trunk.port_id))
        for subport in subports:
            self._add_subport(trunk, subport, df_parent)
        self._update_subport_statuses(trunk.port_id, subports)

    def _update_subport_statuses(self, parent_id, subports):
        core_plugin = directory.get_plugin()
        admin_context = context.get_admin_context()
        parent = core_plugin.get_port(admin_context, parent_id)
        if parent['status'] == n_constants.PORT_STATUS_ACTIVE:
            for subport in subports:
                core_plugin.update_port_status(admin_context,
                                               subport.port_id,
                                               n_constants.PORT_STATUS_ACTIVE)

    def _add_subport(self, trunk, subport, df_parent):
        """
        Create the subport that were created on the Neutron side in the
        Dragonflow NB DB
        """
        model = trunk_models.ChildPortSegmentation(
            id=trunk_models.get_child_port_segmentation_id(trunk.port_id,
                                                           subport.port_id),
            topic=trunk.project_id,
            parent=trunk.port_id,
            port=subport.port_id,
            segmentation_type=subport.segmentation_type,
            segmentation_id=subport.segmentation_id,
        )
        self.nb_api.create(model)

    def _delete_subports_handler(self, *args, **kwargs):
        """Handle the event that subports were deleted"""
        payload = kwargs['payload']
        trunk = payload.current_trunk
        subports = payload.subports
        self._delete_subports(trunk, subports)

    def _delete_subports(self, trunk, subports):
        """
        Remove the subports that were deleted on the Neutron side from the
        Dragonflow NB DB
        """
        df_parent = self.nb_api.get(l2.LogicalPort(id=trunk.port_id))
        for subport in subports:
            self._delete_subport(trunk, subport, df_parent)

    def _delete_subport(self, trunk, subport, df_parent):
        """
        Remove the subport that were deleted on the Neutron side from the
        Dragonflow NB DB
        """
        id_ = trunk_models.get_child_port_segmentation_id(trunk.port_id,
                                                          subport.port_id),
        model = trunk_models.ChildPortSegmentation(
            id=id_,
            topic=trunk.project_id
        )
        self.nb_api.delete(model)

    def _get_child_port_status(self, parent_port):
        new_status = n_constants.PORT_STATUS_ACTIVE
        if parent_port['status'] != n_constants.PORT_STATUS_ACTIVE:
            new_status = n_constants.PORT_STATUS_DOWN
        return new_status

    def _update_port_handler(self, *args, **kwargs):
        """
        Handle the event that a port changes status to ACTIVE or DOWN.
        Also handle modification of allowed address pairs to detect macvlan
        """
        port = kwargs['port']
        orig_port = kwargs['original_port']
        self._detect_macvlan(kwargs['context'], port, orig_port)
        if port['status'] == orig_port['status']:
            return  # Change not relevant
        new_status = self._get_child_port_status(port)
        core_plugin = directory.get_plugin()
        for subport_id in self._get_subports_ids(port['id']):
            core_plugin.update_port_status(context.get_admin_context(),
                                           subport_id, new_status)
        # TODO(oanson) Update MACVLAN port status

    def _get_subports_ids(self, port_id):
        trunk_plugin = directory.get_plugin('trunk')
        filters = {'port_id': port_id}
        trunks = trunk_plugin.get_trunks(context.get_admin_context(),
                                         filters=filters)
        if len(trunks) == 0:
            return ()
        trunk = trunks[0]
        return (subport['port_id'] for subport in trunk['sub_ports'])

    def _symmetric_difference(self, l1, l2):
        diff1 = [e for e in l1 if e not in l2]
        diff2 = [e for e in l2 if e not in l1]
        return diff1, diff2

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
        new_aaps, removed_aaps = self._symmetric_difference(updated_port_aaps, orig_port_aaps)
        core_plugin = directory.get_plugin()
        new_status = self._get_child_port_status(updated_port)
        LOG.info('_detect_macvlan: id: %s updated_port_aaps: %s orig_port_aaps: %s',
                 updated_port['id'], updated_port_aaps, orig_port_aaps)

        for pair in new_aaps:
            try:
                pair_ip = netaddr.IPAddress(pair["ip_address"])
            except ValueError:
                continue  # Skip. This is a network, not a host
            pair_mac = pair.get('mac_address')
            if pair_mac and pair_mac == updated_port['mac_address']:
                pair_mac = None
            macvlan_port = self._find_macvlan_port(a_context, pair_ip, pair_mac)
            if not macvlan_port:
                LOG.info('_detect_macvlan (new): Could not find port with ip/mac %s/%s',
                         pair_ip, pair_mac)
                continue
            cps_id = trunk_models.get_child_port_segmentation_id(
                    updated_port['id'], macvlan_port['id'])
            model = trunk_models.ChildPortSegmentation(
                id=cps_id,
                topic=updated_port['project_id'],
                parent=updated_port['id'],
                port=macvlan_port['id'],
                segmentation_type=trunk_models.TYPE_MACVLAN,
            )
            self.nb_api.create(model)
            core_plugin.update_port_status(context.get_admin_context(),
                                           macvlan_port['id'], new_status)

        for pair in removed_aaps:
            try:
                pair_ip = netaddr.IPAddress(pair["ip_address"])
            except ValueError:
                continue  # Skip. This is a network, not a host
            pair_mac = pair.get('mac_address')
            if pair_mac and pair_mac == updated_port['mac_address']:
                pair_mac = None
            macvlan_port = self._find_macvlan_port(pair_ip, pair_mac)
            if not macvlan_port:
                LOG.info('_detect_macvlan (removed): Could not find port with ip/mac %s/%s',
                         pair_ip, pair_mac)
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

    def _find_macvlan_port(self, context, ip=None, mac_address=None):
        if ip is None and mac_address is None:
            return None
        filters = {}
        if ip:
            filters['fixed_ips'] = {"ip_address": [str(ip)]}
        if mac_address:
            filters['mac_address'] = [str(mac_address)]
        core_plugin = directory.get_plugin()
        ports = core_plugin.get_ports(context, filters=filters)
        LOG.info('_find_macvlan_port: Filters: %s Found: %s', filters, ports)
        if ports:
            return ports[0]
        return None

    def _update_port_aap_handler(self, *args, **kwargs):
        port = kwargs['port']
        orig_port = kwargs['original_port']
        self._detect_macvlan(kwargs['context'], port, orig_port)
        if port.get('status') != orig_port.get('status'):
            LOG.info('Status changed for port %s: %s -> %s',
                      port['id'], orig_port.get('status'), port.get('status'))

    def _create_port_aap_handler(self, *args, **kwargs):
        port = kwargs['port']
        self._detect_macvlan(kwargs['context'], port)
