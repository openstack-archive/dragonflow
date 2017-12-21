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

from neutron_lib import constants as n_const
from oslo_log import log
from ryu.ofproto import ether

from dragonflow.common import exceptions
from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.controller import port_locator
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import trunk

LOG = log.getLogger(__name__)


def _get_classification_params_ip(child_port_segmentation):
    child = child_port_segmentation.port
    child_ip = child.ip
    child_ip_version = child_ip.version
    if child_ip_version == n_const.IP_VERSION_4:
        ip_field = 'ipv4_src'
        eth_type = ether.ETH_TYPE_IP
    elif child_ip_version == n_const.IP_VERSION_6:
        ip_field = 'ipv6_src'
        eth_type = ether.ETH_TYPE_IPV6
    else:
        LOG.warning('Unknown version %s for IP %r',
                    child_ip_version, child_ip)
        raise exceptions.InvalidIPAddressException(key=child_ip)
    return ip_field, eth_type, child_ip


class BaseNestedPortImpl(object):
    def __init__(self, app):
        super(BaseNestedPortImpl, self).__init__()
        self.app = app

    def install_classification_rule(self, child_port_segmentation):
        LOG.debug('%s.install_classification_rule: Enter: %r',
                  type(self), child_port_segmentation)
        match = self.get_classification_match(child_port_segmentation)
        actions = self.get_classification_actions(child_port_segmentation)
        self.app.mod_flow(
            table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            actions=actions,
        )

    def delete_classification_rule(self, child_port_segmentation):
        LOG.debug('%s.delete_classification_rule: Enter: %r',
                  type(self), child_port_segmentation)
        match = self.get_classification_match(child_port_segmentation)
        self.app.mod_flow(
            table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )

    def get_classification_actions(self, child_port_segmentation):
        lport = child_port_segmentation.port
        network_id = lport.lswitch.unique_key
        unique_key = lport.unique_key
        # TODO(oanson) This code is very similar to classifier app.
        actions = [
            self.app.parser.OFPActionSetField(reg6=unique_key),
            self.app.parser.OFPActionSetField(metadata=network_id),
        ]
        additional_actions = self.get_additional_classification_actions(
                child_port_segmentation)
        if additional_actions:
            actions.extend(additional_actions)
        actions.append(self.app.parser.NXActionResubmit())
        return actions

    def get_additional_classification_actions(self, child_port_segmentation):
        pass

    def get_classification_match(self, child_port_segmentation):
        params = {'reg6': child_port_segmentation.parent.unique_key}
        additional_params = self.get_additional_classification_params(
                child_port_segmentation)
        if additional_params:
            params.update(additional_params)
        return self.app.parser.OFPMatch(**params)

    def get_additional_classification_params(self, child_port_segmentation):
        pass

    def install_dispatch_rule(self, child_port_segmentation):
        LOG.debug('%s.install_dispatch_rule: Enter: %r',
                  type(self), child_port_segmentation)
        match = self.get_dispatch_match(child_port_segmentation)
        actions = self.get_dispatch_actions(child_port_segmentation)
        self.app.mod_flow(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            actions=actions,
        )

    def delete_dispatch_rule(self, child_port_segmentation):
        LOG.debug('%s.delete_dispatch_rule: Enter: %r',
                  type(self), child_port_segmentation)
        match = self.get_dispatch_match(child_port_segmentation)
        self.app.mod_flow(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=match,
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
        )

    def get_dispatch_match(self, child_port_segmentation):
        lport = child_port_segmentation.port
        params = {'reg7': lport.unique_key}
        additional_params = self.get_additional_dispatch_params(
                child_port_segmentation)
        if additional_params:
            params.update(additional_params)
        match = self.app.parser.OFPMatch(**params)
        return match

    def get_additional_dispatch_params(self, child_port_segmentation):
        pass

    def get_dispatch_actions(self, child_port_segmentation):
        actions = self.get_additional_dispatch_actions(child_port_segmentation)
        if actions is None:
            actions = []
        parent_port_key = child_port_segmentation.parent.unique_key
        actions += [
            self.app.parser.OFPActionSetField(reg7=parent_port_key),
            self.app.parser.NXActionResubmit(),
        ]
        return actions

    def get_additional_dispatch_actions(self, child_port_segmentation):
        pass


class VlanNestedPortImpl(BaseNestedPortImpl):
    def get_additional_classification_actions(self, child_port_segmentation):
        return [self.app.parser.OFPActionPopVlan()]

    def get_additional_classification_params(self, child_port_segmentation):
        vlan_vid = (self.app.ofproto.OFPVID_PRESENT |
                    child_port_segmentation.segmentation_id)
        params = {'vlan_vid': vlan_vid}
        return params

    def get_additional_dispatch_actions(self, child_port_segmentation):
        vlan_tag = (child_port_segmentation.segmentation_id |
                    self.app.ofproto.OFPVID_PRESENT)
        return [self.app.parser.OFPActionPushVlan(),
                self.app.parser.OFPActionSetField(vlan_vid=vlan_tag)]


class MACVlanNestedPortIPImpl(BaseNestedPortImpl):
    def get_additional_classification_params(self, child_port_segmentation):
        ip_field, eth_type, child_ip = _get_classification_params_ip(
            child_port_segmentation)
        return {'eth_src': child_port_segmentation.port.mac,
                'eth_type': eth_type,
                ip_field: child_ip}

    def get_additional_dispatch_params(self, child_port_segmentation):
        _ip_field, eth_type, _child_ip = _get_classification_params_ip(
            child_port_segmentation)
        return {'eth_type': eth_type}


class IPv4OnlyMixin(object):
    def install_classification_rule(self, child_port_segmentation):
        LOG.debug("install_classification_rule: IPv4 only: Enter")
        child_ip = child_port_segmentation.port.ip
        if child_ip.version != n_const.IP_VERSION_4:
            return
        super(IPv4OnlyMixin, self).install_classification_rule(
                child_port_segmentation)

    def delete_classification_rule(self, child_port_segmentation):
        LOG.debug("delete_classification_rule: IPv4 only: Enter")
        child_ip = child_port_segmentation.port.ip
        if child_ip.version != n_const.IP_VERSION_4:
            return
        super(IPv4OnlyMixin, self).delete_classification_rule(
                child_port_segmentation)

    def install_dispatch_rule(self, child_port_segmentation):
        LOG.debug("install_dispatch_rule: IPv4 only: Enter")
        child_ip = child_port_segmentation.port.ip
        if child_ip.version != n_const.IP_VERSION_4:
            return
        super(IPv4OnlyMixin, self).install_dispatch_rule(
                child_port_segmentation)

    def delete_dispatch_rule(self, child_port_segmentation):
        LOG.debug("delete_dispatch_rule: IPv4 only: Enter")
        child_ip = child_port_segmentation.port.ip
        if child_ip.version != n_const.IP_VERSION_4:
            return
        super(IPv4OnlyMixin, self).delete_dispatch_rule(
                child_port_segmentation)


class MACVlanNestedPortArpImpl(IPv4OnlyMixin, BaseNestedPortImpl):
    def get_additional_classification_params(self, child_port_segmentation):
        return {'eth_src': child_port_segmentation.port.mac,
                'eth_type': ether.ETH_TYPE_ARP,
                'arp_sha': child_port_segmentation.port.mac,
                'arp_spa': child_port_segmentation.port.ip}

    def get_additional_dispatch_params(self, child_port_segmentation):
        return {'eth_type': ether.ETH_TYPE_ARP}


class IPVlanNestedPortIPImpl(BaseNestedPortImpl):
    def get_additional_classification_actions(self, child_port_segmentation):
        child_mac = child_port_segmentation.port.mac
        return [self.app.parser.OFPActionSetField(eth_src=child_mac)]

    def get_additional_classification_params(self, child_port_segmentation):
        ip_field, eth_type, child_ip = _get_classification_params_ip(
            child_port_segmentation)
        parent_mac = child_port_segmentation.parent.mac
        return {'eth_src': parent_mac,
                'eth_type': eth_type,
                ip_field: child_ip}

    def get_additional_dispatch_params(self, child_port_segmentation):
        _ip_field, eth_type, _child_ip = _get_classification_params_ip(
            child_port_segmentation)
        return {'eth_type': eth_type}

    def get_additional_dispatch_actions(self, child_port_segmentation):
        parent_mac = child_port_segmentation.parent.mac
        return [self.app.parser.OFPActionSetField(eth_dst=parent_mac)]


class IPVlanNestedPortArpImpl(IPv4OnlyMixin, BaseNestedPortImpl):
    def get_additional_classification_actions(self, child_port_segmentation):
        child_mac = child_port_segmentation.port.mac
        return [
            self.app.parser.OFPActionSetField(eth_src=child_mac),
            self.app.parser.OFPActionSetField(arp_sha=child_mac),
        ]

    def get_additional_classification_params(self, child_port_segmentation):
        parent_mac = child_port_segmentation.parent.mac
        return {'eth_src': parent_mac,
                'eth_type': ether.ETH_TYPE_ARP,
                'arp_sha': parent_mac,
                'arp_spa': child_port_segmentation.port.ip}

    def get_additional_dispatch_params(self, child_port_segmentation):
        return {'eth_type': ether.ETH_TYPE_ARP}

    def get_additional_dispatch_actions(self, child_port_segmentation):
        parent_mac = child_port_segmentation.parent.mac
        return [
            self.app.parser.OFPActionSetField(eth_dst=parent_mac),
            self.app.parser.OFPActionSetField(arp_tha=parent_mac),
        ]


class TrunkApp(df_base_app.DFlowApp):

    def __init__(self, api, vswitch_api=None, nb_api=None,
                 neutron_server_notifier=None):
        super(TrunkApp, self).__init__(
            api, vswitch_api=vswitch_api,
            nb_api=nb_api,
            neutron_server_notifier=neutron_server_notifier)
        self.segmentation_type_implementations = {
            n_const.TYPE_VLAN: [VlanNestedPortImpl(self)],
            trunk.TYPE_MACVLAN: [MACVlanNestedPortIPImpl(self),
                                 MACVlanNestedPortArpImpl(self)],
            trunk.TYPE_IPVLAN: [IPVlanNestedPortIPImpl(self),
                                IPVlanNestedPortArpImpl(self)],
        }

    @df_base_app.register_event(trunk.ChildPortSegmentation,
                                model_constants.EVENT_CREATED)
    def _child_port_segmentation_created(self, child_port_segmentation):
        parent_port = child_port_segmentation.parent
        parent_binding = port_locator.get_port_binding(parent_port)
        if parent_binding is None:
            LOG.error('Could not find parent binding for CPS: %s',
                      child_port_segmentation)
            return

        if parent_binding.is_local:
            self._install_local_cps(child_port_segmentation)
        else:
            self._install_remote_cps(child_port_segmentation)

    def _get_segmentation_type_implementations(self, child_port_segmentation):
        segmentation_type = child_port_segmentation.segmentation_type
        try:
            return self.segmentation_type_implementations[segmentation_type]
        except KeyError:
            raise exceptions.UnsupportedSegmentationTypeException(
                segmentation_type=segmentation_type
            )

    def _install_local_cps(self, child_port_segmentation):
        implementations = self._get_segmentation_type_implementations(
            child_port_segmentation)
        for implementation in implementations:
            implementation.install_classification_rule(child_port_segmentation)
            implementation.install_dispatch_rule(child_port_segmentation)
        port_locator.copy_port_binding(
            child_port_segmentation.port,
            child_port_segmentation.parent,
        )
        child_port_segmentation.port.emit_bind_local()

    def _install_remote_cps(self, child_port_segmentation):
        port_locator.copy_port_binding(
            child_port_segmentation.port,
            child_port_segmentation.parent,
        )
        child_port_segmentation.port.emit_bind_remote()

    @df_base_app.register_event(trunk.ChildPortSegmentation,
                                model_constants.EVENT_DELETED)
    def _child_port_segmentation_deleted(self, child_port_segmentation):
        parent_port = child_port_segmentation.parent
        parent_binding = port_locator.get_port_binding(parent_port)
        if parent_binding is None:
            return

        if parent_binding.is_local:
            self._uninstall_local_cps(child_port_segmentation)
        else:
            self._uninstall_remote_cps(child_port_segmentation)

    def _uninstall_local_cps(self, child_port_segmentation):
        child_port_segmentation.port.emit_unbind_local()
        port_locator.clear_port_binding(child_port_segmentation.port)
        implementations = self._get_segmentation_type_implementations(
            child_port_segmentation)
        for implementation in implementations:
            implementation.delete_classification_rule(child_port_segmentation)
            implementation.delete_dispatch_rule(child_port_segmentation)

    def _uninstall_remote_cps(self, child_port_segmentation):
        child_port_segmentation.port.emit_unbind_remote()
        port_locator.clear_port_binding(child_port_segmentation.port)

    def _get_all_cps_by_parent(self, lport):
        return self.db_store.get_all(
            trunk.ChildPortSegmentation(parent=lport.id),
            index=trunk.ChildPortSegmentation.get_index('parent_id'),
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _local_port_bound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._install_local_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _local_port_unbound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._uninstall_local_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    def _remote_port_bound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._install_remote_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    def _remote_port_unbound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._uninstall_remote_cps(cps)
