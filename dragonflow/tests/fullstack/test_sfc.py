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
import time

import mock
from neutron_lib import constants
from oslo_log import log
from ryu.lib.packet import ether_types
from ryu.lib.packet import ethernet
from ryu.lib.packet import in_proto as inet
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import mpls
from ryu.lib.packet import packet
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
import testscenarios

from dragonflow.db.models import l2
from dragonflow.db.models import sfc
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


IPV4_CIDR = '192.168.19.0/24'
IPV4_ALLOCATION_POOL = ('192.168.19.30', '192.168.19.254')
IPV6_CIDR = '2001:db9::1/64'
IPV6_ALLOCATION_POOL = ('2001:db9::30', '2001:db9::99')

SRC_IPV4_1 = '192.168.19.11'
SRC_IPV4_2 = '192.168.19.12'
DST_IPV4_1 = '192.168.19.21'
DST_IPV4_2 = '192.168.19.22'

SRC_IPV6_1 = '2001:db9::11'
SRC_IPV6_2 = '2001:db9::12'
DST_IPV6_1 = '2001:db9::21'
DST_IPV6_2 = '2001:db9::22'

SRC_PORT = 2222
DST_PORT = 4444

load_tests = testscenarios.load_tests_apply_scenarios

# We could use the default 30sec timeout here but testing showed that 5 seconds
# is was good enough, double that and the 20 secs still save almost 10 minutes
# in total.
_QUICK_RESOURCE_READY_TIMEOUT = 10


class SfcTestsCommonBase(test_base.DFTestBase):
    def _create_sf_port(self):
        port = self.subnet.create_port([self.security_group.secgroup_id])
        port.update({'device_id': 'device1'})
        return port

    @classmethod
    def _parse_sfc_packet(cls, buf):
        # NOTE (dimak) Ruy's mpls class always parses its payload as ipv4.
        # since we also test with ipv6 packets, we monkeypatch its parse
        # method to try ipv6 as next protocol.
        orig_parser = mpls.mpls.parser

        for cls in (ipv4.ipv4, ipv6.ipv6):

            def parser(*args, **kwargs):
                res = orig_parser(*args, **kwargs)
                return res[0], cls, res[2]

            with mock.patch(
                'ryu.lib.packet.mpls.mpls.parser', side_effect=parser,
            ):
                pkt = packet.Packet(buf)
            if not isinstance(pkt.protocols[-1], mpls.mpls):
                return pkt

        raise ValueError(buf)

    @classmethod
    def _sf_callback(cls, buf):
        '''This is the code each SF runs, increments all chars in payload.
        '''
        pkt = cls._parse_sfc_packet(buf)

        protocols = pkt.protocols[:-1]
        payload = bytearray(pkt.protocols[-1])

        new_payload = bytearray(c + 1 for c in payload)

        new_pkt = packet.Packet()
        for protocol in protocols:
            if hasattr(protocol, 'csum'):
                protocol.csum = 0

            new_pkt.add_protocol(protocol)

        new_pkt.add_protocol(new_payload)
        new_pkt.serialize()
        return new_pkt.data

    def _create_pp(self):
        ingress = self._create_sf_port()
        egress = self._create_sf_port()

        pp = self.store(objects.PortPairTestObj(self.neutron, self.nb_api))
        pp.create_from_ports(
            ingress=ingress,
            egress=egress,
            type_=self.corr,
        )

        return pp

    def _create_ppg(self, width):
        pps = [self._create_pp() for _ in range(width)]
        ppg = self.store(
            objects.PortPairGroupTestObj(self.neutron, self.nb_api))
        ppg.create_from_portpairs(pps)
        return ppg

    def _create_pc(self, fc, layout):
        ppgs = [self._create_ppg(w) for w in layout]
        pc = self.store(
            objects.PortChainTestObj(self.neutron, self.nb_api))
        pc.create_from_fcs_ppgs([fc], ppgs)
        return pc

    def setUp(self):
        super(SfcTestsCommonBase, self).setUp()

        self.security_group = self.store(objects.SecGroupTestObj(
            self.neutron,
            self.nb_api))

        security_group_id = self.security_group.create()
        self.assertTrue(self.security_group.exists())

        for direction, ethertype, protocol in itertools.product(
            ('ingress', 'egress'),
            (constants.IPv4, constants.IPv6),
            (constants.PROTO_NAME_TCP, constants.PROTO_NAME_UDP),
        ):
            rule = {
                'direction': direction,
                'ethertype': ethertype,
                'protocol': protocol,
                'port_range_min': 1,
                'port_range_max': 65535,
            }
            rule_id = self.security_group.rule_create(secrule=rule)
            self.assertTrue(self.security_group.rule_exists(rule_id))

        self.topology = self.store(
            app_testing_objects.Topology(
                self.neutron,
                self.nb_api,
            ),
        )

        self.subnet = self.topology.create_subnet(
            cidr=IPV4_CIDR,
            enable_dhcp=True,
            allocation_pool=IPV4_ALLOCATION_POOL,
        )
        self.subnet_ipv6 = self.topology.create_subnet(
            cidr=IPV6_CIDR,
            enable_dhcp=True,
            allocation_pool=IPV6_ALLOCATION_POOL,
        )

        self.src_port = self.subnet.create_port([security_group_id])
        self.dst_port = self.subnet.create_port([security_group_id])

        self.src_port.update({
            'name': 'src_port',
            'admin_state_up': True,
            'fixed_ips': [
                {'ip_address': SRC_IPV4_1},
                {'ip_address': SRC_IPV4_2},
                {'ip_address': SRC_IPV6_1},
                {'ip_address': SRC_IPV6_2},
            ],
        })

        self.dst_port.update({
            'name': 'dst_port',
            'admin_state_up': True,
            'fixed_ips': [
                {'ip_address': DST_IPV4_1},
                {'ip_address': DST_IPV4_2},
                {'ip_address': DST_IPV6_1},
                {'ip_address': DST_IPV6_2},
            ],
        })

        self.src_lport = self.nb_api.get(
            l2.LogicalPort(id=self.src_port.port.port_id),
        )
        self.dst_lport = self.nb_api.get(
            l2.LogicalPort(id=self.dst_port.port.port_id),
        )

    def _create_port_policies(self, pc):
        res = {}
        if self.corr == sfc.CORR_MPLS:
            sf_filter = app_testing_objects.RyuMplsFilter()
        else:
            sf_filter = app_testing_objects.RyuUdpFilter(DST_PORT)

        for _, ppg in enumerate(pc.port_pair_groups):
            for _, pp in enumerate(ppg.port_pairs):
                key = (self.subnet.subnet_id, pp.ingress.port_id)
                res[key] = app_testing_objects.PortPolicy(
                    rules=[
                        app_testing_objects.PortPolicyRule(
                            sf_filter,
                            actions=[
                                app_testing_objects.SendAction(
                                    self.subnet.subnet_id,
                                    pp.egress.port_id,
                                    self._sf_callback,
                                ),
                            ],
                        ),
                    ],
                    default_action=app_testing_objects.IgnoreAction(),
                )
        return res

    def _gen_ethernet(self, src=None, dst=None, ethertype=None):
        return ethernet.ethernet(
            src=(src or self.src_lport.mac),
            dst=(dst or self.dst_lport.mac),
            ethertype=(ethertype or ether_types.ETH_TYPE_IP),
        )

    def _gen_ipv4(self, proto, src=None, dst=None):
        return ipv4.ipv4(
            src=(src or SRC_IPV4_1),
            dst=(dst or DST_IPV4_1),
            proto=proto,
        )

    def _gen_ipv6(self, nxt, src=None, dst=None):
        return ipv6.ipv6(
            src=(src or SRC_IPV6_1),
            dst=(dst or DST_IPV6_1),
            nxt=nxt,
        )

    @classmethod
    def _gen_udp(cls, src_port=SRC_PORT, dst_port=DST_PORT):
        return udp.udp(
            src_port=src_port,
            dst_port=dst_port,
        )

    @classmethod
    def _gen_tcp(cls, src_port=SRC_PORT, dst_port=DST_PORT, bits=tcp.TCP_SYN):
        return tcp.tcp(
            src_port=src_port,
            dst_port=dst_port,
            bits=bits,
        )

    @classmethod
    def _get_bytes(cls, pkt):
        pkt.serialize()
        return pkt.data


def _make_scenario(name, **kwargs):
    return (
        name,
        {
            'pkt_ipver': kwargs.get('pkt_ipver', constants.IP_VERSION_4),
            'pkt_proto': kwargs.get('pkt_proto', constants.PROTO_NAME_UDP),
            'fc_lport_type': kwargs.get('fc_lport_type', 'src'),
            'fc_ipver': kwargs.get('fc_ipver'),
            'fc_ip_src': kwargs.get('fc_ip_src'),
            'fc_ip_dst': kwargs.get('fc_ip_dst'),
            'fc_proto': kwargs.get('fc_proto'),
            'fc_src_tp_range': kwargs.get('fc_src_tp_range'),
            'fc_dst_tp_range': kwargs.get('fc_dst_tp_range'),
            'fc_matches': kwargs['fc_matches'],
        }
    )


class TestFcApp(SfcTestsCommonBase):
    corr = 'mpls'

    scenarios = [
        _make_scenario(
            'src_lport',
            fc_lport_type='src',
            fc_matches=True,
        ),
        _make_scenario(
            'dst_lport',
            fc_lport_type='dst',
            fc_matches=True,
        ),
        _make_scenario(
            'ipv4',
            pkt_ipver=constants.IP_VERSION_4,
            fc_ipver=constants.IP_VERSION_4,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv4_negative',
            pkt_ipver=constants.IP_VERSION_4,
            fc_ipver=constants.IP_VERSION_6,
            fc_matches=False,
        ),
        _make_scenario(
            'ipv6',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_6,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv6_negative',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_4,
            fc_matches=False
        ),
        _make_scenario(
            'ipv4_src_cidr',
            fc_ipver=constants.IP_VERSION_4,
            fc_ip_src=SRC_IPV4_1,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv4_src_cidr_negative',
            fc_ipver=constants.IP_VERSION_4,
            fc_ip_src=SRC_IPV4_2,
            fc_matches=False,
        ),
        _make_scenario(
            'ipv4_dst_cidr',
            fc_ipver=constants.IP_VERSION_4,
            fc_ip_dst=DST_IPV4_1,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv4_dst_cidr_negative',
            fc_ipver=constants.IP_VERSION_4,
            fc_ip_dst=DST_IPV4_2,
            fc_matches=False,
        ),
        _make_scenario(
            'ipv6_src_cidr',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_6,
            fc_ip_src=SRC_IPV6_1,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv6_src_cidr_negative',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_6,
            fc_ip_src=SRC_IPV6_2,
            fc_matches=False,
        ),
        _make_scenario(
            'ipv6_dst_cidr',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_6,
            fc_ip_dst=DST_IPV6_1,
            fc_matches=True,
        ),
        _make_scenario(
            'ipv6_dst_cidr_negative',
            pkt_ipver=constants.IP_VERSION_6,
            fc_ipver=constants.IP_VERSION_6,
            fc_ip_dst=DST_IPV6_2,
            fc_matches=False,
        ),
        _make_scenario(
            'proto_tcp',
            pkt_proto=constants.PROTO_NAME_TCP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_TCP,
            fc_matches=True,
        ),
        _make_scenario(
            'proto_udp',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_UDP,
            fc_matches=True,
        ),
        _make_scenario(
            'proto_negative',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_TCP,
            fc_matches=False,
        ),
        _make_scenario(
            'src_ports',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_UDP,
            fc_src_tp_range=[SRC_PORT - 1, SRC_PORT + 1],
            fc_matches=True,
        ),
        _make_scenario(
            'src_ports_negative',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_UDP,
            fc_src_tp_range=[SRC_PORT + 1, SRC_PORT + 2],
            fc_matches=False,
        ),
        _make_scenario(
            'dst_ports',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_UDP,
            fc_dst_tp_range=[DST_PORT - 1, DST_PORT + 1],
            fc_matches=True,
        ),
        _make_scenario(
            'dst_ports_negative',
            pkt_proto=constants.PROTO_NAME_UDP,
            fc_ipver=constants.IP_VERSION_4,
            fc_proto=constants.PROTO_NAME_UDP,
            fc_dst_tp_range=[DST_PORT + 1, DST_PORT + 2],
            fc_matches=False,
        ),
    ]

    @property
    def _fc_params(self):
        IPVER_TO_MASK = {
            constants.IP_VERSION_4: constants.IPv4_BITS,
            constants.IP_VERSION_6: constants.IPv6_BITS,
        }

        params = {}
        if self.fc_lport_type == 'src':
            params['logical_source_port'] = self.src_lport.id
        elif self.fc_lport_type == 'dst':
            params['logical_destination_port'] = self.dst_lport.id

        if self.fc_ipver == constants.IP_VERSION_4:
            params['ethertype'] = constants.IPv4
        elif self.fc_ipver == constants.IP_VERSION_6:
            params['ethertype'] = constants.IPv6

        if self.fc_ip_src is not None:
            params['source_ip_prefix'] = '{addr}/{mask}'.format(
                addr=self.fc_ip_src,
                mask=IPVER_TO_MASK[self.fc_ipver],
            )

        if self.fc_ip_dst is not None:
            params['destination_ip_prefix'] = '{addr}/{mask}'.format(
                addr=self.fc_ip_dst,
                mask=IPVER_TO_MASK[self.fc_ipver],
            )

        if self.fc_proto is not None:
            params['protocol'] = self.fc_proto

        if self.fc_src_tp_range is not None:
            params['source_port_range_min'] = self.fc_src_tp_range[0]
            params['source_port_range_max'] = self.fc_src_tp_range[1]

        if self.fc_dst_tp_range is not None:
            params['destination_port_range_min'] = self.fc_dst_tp_range[0]
            params['destination_port_range_max'] = self.fc_dst_tp_range[1]

        return params

    @property
    def _initial_packet(self):
        payload = '0' * 64

        if self.pkt_proto == constants.PROTO_NAME_TCP:
            tp = self._gen_tcp()
            proto = inet.IPPROTO_TCP
        elif self.pkt_proto == constants.PROTO_NAME_UDP:
            tp = self._gen_udp()
            proto = inet.IPPROTO_UDP

        if self.pkt_ipver == constants.IP_VERSION_4:
            nw = self._gen_ipv4(proto)
            ethertype = ether_types.ETH_TYPE_IP
        else:
            nw = self._gen_ipv6(proto)
            ethertype = ether_types.ETH_TYPE_IPV6

        return self._get_bytes(
            self._gen_ethernet(ethertype=ethertype) / nw / tp / payload
        )

    @property
    def _final_packet(self):
        packet = self._initial_packet

        if self.fc_matches:
            packet = self._sf_callback(packet)

        return packet

    def test_fc(self):
        fc = self.store(
            objects.FlowClassifierTestObj(self.neutron, self.nb_api),
        )
        fc.create(self._fc_params)
        pc = self._create_pc(fc, [1])
        time.sleep(_QUICK_RESOURCE_READY_TIMEOUT)
        dst_key = (self.subnet.subnet_id, self.dst_port.port_id)
        port_policies = {
            dst_key: app_testing_objects.PortPolicy(
                rules=[
                    app_testing_objects.PortPolicyRule(
                        app_testing_objects.ExactMatchFilter(
                            self._final_packet,
                        ),
                        actions=[app_testing_objects.StopSimulationAction()],
                    ),
                ],
                default_action=app_testing_objects.IgnoreAction(),
            ),
        }
        port_policies.update(self._create_port_policies(pc))
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.src_port.port_id,
                        self._initial_packet,
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.LogAction()
            ),
        )
        policy.start(self.topology)
        policy.wait(10)

        if policy.exceptions:
            raise policy.exceptions[0]


class TestSfcApp(SfcTestsCommonBase):
    scenarios = testscenarios.scenarios.multiply_scenarios(
        [
            ('corr-none', {'corr': None}),
            ('corr-mpls', {'corr': sfc.CORR_MPLS}),
        ],
        [
            ('single-ppg', {'layout': (1,)}),
            ('single-wide-ppg', {'layout': (3,)}),
            ('three-ppgs', {'layout': (1, 1, 1)}),
            ('mixed-ppgs', {'layout': (2, 1, 3)}),
        ],
    )

    def test_sfc(self):
        initial_packet = self._get_bytes(
            self._gen_ethernet() /
            self._gen_ipv4(proto=inet.IPPROTO_UDP) /
            self._gen_udp(src_port=SRC_PORT, dst_port=DST_PORT) /
            ('0' * 64)
        )
        final_packet = self._get_bytes(
            self._gen_ethernet() /
            self._gen_ipv4(proto=inet.IPPROTO_UDP) /
            self._gen_udp(src_port=SRC_PORT, dst_port=DST_PORT) /
            ('{len}'.format(len=len(self.layout)) * 64)
        )
        fc = self.store(
            objects.FlowClassifierTestObj(self.neutron, self.nb_api),
        )
        fc.create(
            {
                'logical_source_port': self.src_port.port.port_id
            },
        )
        pc = self._create_pc(fc, self.layout)
        time.sleep(_QUICK_RESOURCE_READY_TIMEOUT)
        dst_key = (self.subnet.subnet_id, self.dst_port.port_id)
        port_policies = {
            dst_key: app_testing_objects.PortPolicy(
                rules=[
                    app_testing_objects.PortPolicyRule(
                        app_testing_objects.ExactMatchFilter(final_packet),
                        actions=[app_testing_objects.StopSimulationAction()],
                    ),
                ],
                default_action=app_testing_objects.IgnoreAction(),
            ),
        }
        port_policies.update(self._create_port_policies(pc))
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.src_port.port_id,
                        initial_packet,
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.LogAction()
            ),
        )
        policy.start(self.topology)
        policy.wait(10)

        if policy.exceptions:
            raise policy.exceptions[0]
