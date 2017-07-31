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


def _is_lport_ref_eq(lport_ref, lport):
    return lport_ref is not None and lport_ref.id == lport.id


class FcApp(df_base_app.DFlowApp):
    def switch_features_handler(self, ev):
        # Add SFC short-circuit in case SFC app is not loaded
        self.add_flow_go_to_table(constants.SFC_ENCAP_TABLE,
                                  constants.PRIORITY_DEFAULT,
                                  constants.SFC_END_OF_CHAIN_TABLE)

    def _flow_classifiers_by_lport(self, lport):
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

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _local_lport_added(self, lport):
        for fc in self._flow_classifiers_by_lport(lport):
            # Install classification/dispatch only if it wasn't installed by
            # _install_flow_classifier
            if _is_lport_ref_eq(fc.source_port, lport):
                self._install_classification_flows(fc)
            elif _is_lport_ref_eq(fc.dest_port, lport):
                self._install_dispatch_flows(fc)

    def _install_flow_classifier(self, flow_classifier):
        # If FC is on a source lport, install flows only when its local
        # If FC is on a dest lport, install everywhere, we can start the chain
        # here and save a few hops.
        if flow_classifier.is_classification_local:
            self._install_classification_flows(flow_classifier)

        # If FC is on a source lport, install flows everywhere. We won't go
        # through the classifier app again so reg6 will not be set.
        # If FC is on a dest lport, install only on local chassis, to avoid
        # reclassification.
        if flow_classifier.is_dispatch_local:
            self._install_dispatch_flows(flow_classifier)

    def _install_classification_flows(self, flow_classifier):
        # FIXME (dimak) assume port is on the types supported by classifier app
        for match in self._create_matches(flow_classifier):
            self.mod_flow(
                table_id=self._get_flow_classifier_table(flow_classifier),
                priority=constants.PRIORITY_VERY_HIGH,
                match=match,
                inst=[
                    self.parser.OFPInstructionActions(
                        self.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.parser.OFPActionSetField(
                                reg2=flow_classifier.unique_key),
                        ],
                    ),
                    self.parser.OFPInstructionGotoTable(
                        constants.SFC_ENCAP_TABLE,
                    ),
                ],
            )

    def _install_dispatch_flows(self, flow_classifier):
        lport = self._get_flow_classifier_lport(flow_classifier)
        # End-of-chain
        # 1) Restore network ID in metadata and zero reg6 + reg2
        # 2) Restore port ID in reg7 in dest port
        # 3) Resubmit to the next table
        lswitch = lport.lswitch

        actions = [
            self.parser.OFPActionSetField(metadata=lswitch.unique_key),
            self.parser.OFPActionSetField(reg6=0),
            self.parser.OFPActionSetField(reg2=0),
        ]

        if flow_classifier.source_port == lport:
            done_bit = _SRC_BIT
        elif flow_classifier.dest_port == lport:
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
            self.parser.NXActionResubmitTable(
                table_id=self._get_flow_classifier_table(flow_classifier))
        ]

        self.mod_flow(
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=self.parser.OFPMatch(reg2=flow_classifier.unique_key),
            actions=actions,
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        for fc in self._flow_classifiers_by_lport(lport):
            # Remove classification/dispatch only if they're no longer needed
            if _is_lport_ref_eq(fc.source_port, lport):
                self._uninstall_classification_flows(fc)
            elif _is_lport_ref_eq(fc.dest_port, lport):
                self._uninstall_dispatch_flows(fc)

    def _uninstall_flow_classifier(self, flow_classifier):
        if flow_classifier.is_classification_local:
            self._uninstall_classification_flows(flow_classifier)

        if flow_classifier.is_dispatch_local:
            self._uninstall_dispatch_flows(flow_classifier)

    def _uninstall_classification_flows(self, flow_classifier):
        # ORIGIN TABLE => SFC ENCAP TABLE
        for match in self._create_matches(flow_classifier):
            self.mod_flow(
                command=self.ofproto.OFPFC_DELETE_STRICT,
                table_id=self._get_flow_classifier_table(flow_classifier),
                priority=constants.PRIORITY_VERY_HIGH,
                match=match,
            )

    def _uninstall_dispatch_flows(self, flow_classifier):
        # SFC_END_OF_CHAIN_TABLE => NEXT TABLE
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=self.parser.OFPMatch(reg2=flow_classifier.unique_key),
        )

    def _get_flow_classifier_table(self, flow_classifier):
        if flow_classifier.source_port is not None:
            return constants.L2_LOOKUP_TABLE
        elif flow_classifier.dest_port is not None:
            return constants.EGRESS_TABLE
        else:
            raise ValueError(
                _('Neither source not destination port specified'))

    def _get_flow_classifier_lport(self, flow_classifier):
        return flow_classifier.source_port or flow_classifier.dest_port

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_CREATED)
    def _port_chain_created(self, port_chain):
        for fc in port_chain.flow_classifiers:
            self._install_flow_classifier(fc)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_DELETED)
    def _port_chain_deleted(self, port_chain):
        for fc in port_chain.flow_classifiers:
            self._uninstall_flow_classifier(fc)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_UPDATED)
    def _port_chain_updated(self, port_chain, old_port_chain):
        old_fcs = set(fc.id for fc in old_port_chain.flow_classifiers)
        new_fcs = set(fc.id for fc in port_chain.flow_classifiers)

        added_fcs = new_fcs - old_fcs
        deleted_fcs = old_fcs - new_fcs

        for fc_id in deleted_fcs:
            fc = old_port_chain.find_flow_classifier(fc_id)
            self._uninstall_flow_classifier(fc)

        for fc_id in added_fcs:
            fc = port_chain.find_flow_classifier(fc_id)
            self._install_flow_classifier(fc)

    def _create_matches(self, flow_classifier):
        params = {}

        if flow_classifier.source_port is not None:
            lport = flow_classifier.source_port
            params['reg6'] = lport.unique_key
            params['reg3'] = (_SRC_NOT_DONE, _SRC_MASK)

        if flow_classifier.dest_port is not None:
            lport = flow_classifier.dest_port
            params['reg7'] = lport.unique_key
            params['reg3'] = (_DST_NOT_DONE, _DST_MASK)

        if flow_classifier.ether_type is not None:
            if flow_classifier.ether_type == lib_constants.IPv4:
                params.update(_create_ipv4_params(flow_classifier))
            elif flow_classifier.ether_type == lib_constants.IPv6:
                params.update(_create_ipv6_params(flow_classifier))
            else:
                raise RuntimeError(
                    _('Unsupported ethertype {0}').format(
                        flow_classifier.ether_type))

        param_list = [params]

        if flow_classifier.protocol is not None:
            if flow_classifier.protocol == lib_constants.PROTO_NAME_TCP:
                l4_params = _create_tcp_params(flow_classifier)
            elif flow_classifier.protocol == lib_constants.PROTO_NAME_UDP:
                l4_params = _create_udp_params(flow_classifier)
            else:
                raise RuntimeError(
                    _('Unsupported protocol {0}').format(
                        flow_classifier.protocol))

            param_list = _multiply_params(param_list, l4_params)

        return (self.parser.OFPMatch(**p) for p in param_list)


def _multiply_params(old_params, new_params):
    '''Create combined dictionaries for all pairs of (old, new) params.

    Example:
    >>> _multiply_params([{a: 1}, {a: 2}], [{b: 1}, {b:2}])
    [{a:1, b:1}, {a:1, b:2}, {a:2, b:1}, {a:2, b:2}]
    '''
    res = []
    for base, new in itertools.product(old_params, new_params):
        p = base.copy()
        p.update(new)
        res.append(p)
    return res


def _create_ipv4_params(fc):
    return _create_ip_params(
        fc, ether_types.ETH_TYPE_IP, 'ipv4_src', 'ipv4_dst')


def _create_ipv6_params(fc):
    return _create_ip_params(
        fc, ether_types.ETH_TYPE_IPV6, 'ipv6_src', 'ipv6_dst')


def _create_ip_params(fc, eth_type, src_label, dst_label):
    params = {'eth_type': eth_type}

    if fc.source_cidr is not None:
        params[src_label] = (
            int(fc.source_cidr.network),
            int(fc.source_cidr.netmask),
        )

    if fc.dest_cidr is not None:
        params[dst_label] = (
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
