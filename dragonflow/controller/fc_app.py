# Copyright (c) 2016 OpenStack Foundation.
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
import itertools

from neutron_lib import constants as lib_constants
from oslo_log import log
from ryu.lib.packet import ether_types
from ryu.lib.packet import in_proto
from ryu.ofproto import nicira_ext

from dragonflow._i18n import _
from dragonflow.controller.common import constants
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import l2
from dragonflow.db.models import sfc

LOG = log.getLogger(__name__)

# We're using 2 least significant bits of reg3 to mark if we already classified
# the packet or not (to avoid infinite loops)
_SRC_NOT_DONE = 0
_SRC_DONE = 1
_SRC_BIT = 0
_SRC_MASK = (1 << _SRC_BIT)

_DST_NOT_DONE = 0
_DST_DONE = 2
_DST_BIT = 1
_DST_MASK = (1 << _DST_BIT)


class FcApp(df_base_app.DFlowApp):
    def switch_features_handler(self, ev):
        # Add SFC short-circuit in case SFC app is not loaded
        self.add_flow_go_to_table(constants.SFC_ENCAP_TABLE,
                                  constants.PRIORITY_DEFAULT,
                                  constants.SFC_END_OF_CHAIN_TABLE)

    def _get_fcs_by_lport(self, lport):
        return itertools.chain(
            self.db_store.get_all(
                sfc.FlowClassifier(source_port=lport),
                index=sfc.FlowClassifier.get_index('source_port'),
            ),
            self.db_store.get_all(
                sfc.FlowClassifier(dest_port=lport),
                index=sfc.FlowClassifier.get_index('dest_port'),
            ),
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _local_lport_added(self, lport):
        for fc in self._get_fcs_by_lport(lport):
            self._install_flow_classifier(fc)

    def _install_flow_classifier(self, fc):
        # If FC is on a source lport, install flows only when its local
        # If FC is on a dest lport, install everywhere, we can start the chain
        # here and save a few hops.
        if fc.is_classification_local:
            self._install_classification_flows(fc)

        # If FC is on a source lport, install flows everywhere. We won't go
        # through the classifier app again so reg6 will not be set.
        # If FC is on a dest lport, install only on local chassis, to avoid
        # reclassification.
        if fc.is_dispatch_local:
            self._install_dispatch_flows(fc)

    def _install_classification_flows(self, fc):
        # FIXME (dimak) assume lport is a vm port for now
        for match in self._create_matches(fc):
            self.mod_flow(
                table_id=self._get_fc_table(fc),
                priority=constants.PRIORITY_VERY_HIGH,
                match=match,
                inst=[
                    self.parser.OFPInstructionActions(
                        self.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.parser.OFPActionSetField(reg6=fc.unique_key),
                        ],
                    ),
                    self.parser.OFPInstructionGotoTable(
                        constants.SFC_ENCAP_TABLE,
                    ),
                ],
            )

    def _install_dispatch_flows(self, fc):
        lport = self._get_fc_lport(fc)
        # End-of-chain
        # 1) Restore network ID in metadata
        # 2) Restore port ID in reg6/reg7
        # 3) Resubmit to the next table
        lswitch = lport.lswitch

        actions = [self.parser.OFPActionSetField(metadata=lswitch.unique_key)]

        if fc.source_port == lport:
            done_bit = _SRC_BIT
        elif fc.dest_port == lport:
            done_bit = _DST_BIT

            # FIXME (dimak) maybe get it from L2 table
            actions.append(
                self.parser.OFPActionSetField(reg7=lport.unique_key)
            )

        actions += [
            self.parser.NXActionRegLoad(
                dst='reg3',
                value=1,
                ofs_nbits=nicira_ext.ofs_nbits(done_bit, done_bit),
            ),
            self.parser.NXActionResubmitTable(table_id=self._get_fc_table(fc))
        ]

        self.mod_flow(
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=self.parser.OFPMatch(reg6=fc.unique_key),
            actions=actions,
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        for fc in self._get_fcs_by_lport(lport):
            self._uninstall_flow_classifier(fc)

    def _uninstall_flow_classifier(self, fc):
        if fc.is_classification_local:
            # ORIGIN TABLE => SFC ENCAP TABLE
            for match in self._create_matches(fc):
                self.mod_flow(
                    command=self.ofproto.OFPFC_DELETE_STRICT,
                    table_id=self._get_fc_table(fc),
                    priority=constants.PRIORITY_VERY_HIGH,
                    match=match,
                )

        if fc.is_dispatch_local:
            # SFC_END_OF_CHAIN_TABLE => NEXT TABLE
            self.mod_flow(
                command=self.ofproto.OFPFC_DELETE_STRICT,
                table_id=constants.SFC_END_OF_CHAIN_TABLE,
                priority=constants.PRIORITY_MEDIUM,
                match=self.parser.OFPMatch(reg6=fc.unique_key),
            )

    def _get_fc_table(self, fc):
        if fc.source_port is not None:
            return constants.L2_LOOKUP_TABLE
        elif fc.dest_port is not None:
            return constants.EGRESS_TABLE
        else:
            raise ValueError(
                _('Neither source not destination port specified'))

    def _get_fc_lport(self, fc):
        return fc.source_port or fc.dest_port

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_CREATED)
    def _sfc_portchain_created(self, pc):
        for fc in pc.flow_classifiers:
            self._install_flow_classifier(fc)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_DELETED)
    def _sfc_portchain_deleted(self, pc):
        for fc in pc.flow_classifiers:
            self._uninstall_flow_classifier(fc)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_UPDATED)
    def _sfc_portchain_updated(self, pc, old_pc):
        old_fcs = set(fc.id for fc in old_pc.flow_classifiers)
        new_fcs = set(fc.id for fc in pc.flow_classifiers)

        added_fcs = new_fcs - old_fcs
        deleted_fcs = old_fcs - new_fcs

        for fc_id in deleted_fcs:
            fc = old_pc.find_flow_classifier(fc_id)
            self._uninstall_flow_classifier(fc)

        for fc_id in added_fcs:
            fc = pc.find_flow_classifier(fc_id)
            self._install_flow_classifier(fc)

    def _create_matches(self, fc):
        params = {}

        if fc.source_port is not None:
            lport = fc.source_port
            params['reg6'] = lport.unique_key
            params['reg3'] = (_SRC_NOT_DONE, _SRC_MASK)

        if fc.dest_port is not None:
            lport = fc.dest_port
            params['reg7'] = lport.unique_key
            params['reg3'] = (_DST_NOT_DONE, _DST_MASK)

        if fc.ether_type is not None:
            if fc.ether_type == lib_constants.IPv4:
                params.update(_create_ipv4_params(fc))
            elif fc.ether_type == lib_constants.IPv6:
                params.update(_create_ipv6_params(fc))
            else:
                raise RuntimeError(
                    _('Unsupported ethertype {0}').format(fc.ether_type))

        param_list = [params]

        if fc.protocol is not None:
            if fc.protocol == lib_constants.PROTO_NAME_TCP:
                l4_params = _create_tcp_params(fc)
            elif fc.protocol == lib_constants.PROOT_NAME_UDP:
                l4_params = _create_udp_params(fc)
            else:
                raise RuntimeError(
                    _('Unsupported protocol {0}').format(fc.protocol))

            param_list = _multiply_params(param_list, l4_params)

        return (self.parser.OFPMatch(**p) for p in param_list)


def _multiply_params(old_params, new_params):
    res = []
    for base, new in itertools.product(old_params, new_params):
        p = base.copy()
        p.update(new)
        res.append(p)
    return res


def _create_ipv4_params(fc):
    params = {}
    params['eth_type'] = ether_types.ETH_TYPE_IP

    if fc.source_cidr is not None:
        params['ipv4_src'] = (
            int(fc.source_cidr.network),
            int(fc.source_cidr.netmask),
        )

    if fc.dest_cidr is not None:
        params['ipv4_dst'] = (
            int(fc.dest_cidr.network),
            int(fc.dest_cidr.netmask),
        )

    return params


def _create_ipv6_params(fc):
    params = {}
    params['eth_type'] = ether_types.ETH_TYPE_IPV6

    if fc.source_cidr is not None:
        params['ipv6_src'] = (
            int(fc.source_cidr.network),
            int(fc.source_cidr.netmask),
        )

    if fc.dest_cidr is not None:
        params['ipv6_dst'] = (
            int(fc.dest_cidr.network),
            int(fc.dest_cidr.netmask),
        )

    return params


def _create_l4_port_params(fc, proto, src_label, dst_label):
    params = [{'ip_proto': proto}]

    if fc.source_transport_ports is not None:
        source_port_params = utils.get_port_match_list_from_port_range(
            fc.source_transport_ports.min,
            fc.source_transport_ports.max,
        )

        params = _multiply_params(
            params,
            [{src_label: s} for s in source_port_params],
        )

    if fc.dest_transport_ports is not None:
        dest_port_params = utils.get_port_match_list_from_port_range(
            fc.dest_transport_ports.min,
            fc.dest_transport_ports.max,
        )

        params = _multiply_params(
            params,
            [{dst_label: d} for d in dest_port_params],
        )

    return params


def _create_tcp_params(fc):
    return _create_l4_port_params(fc, in_proto.IPPROTO_TCP,
                                  'tcp_src', 'tcp_dst')


def _create_udp_params(fc):
    return _create_l4_port_params(fc, in_proto.IPPROTO_UDP,
                                  'udp_src', 'udp_dst')
