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
from oslo_log import log
import ryu.lib.packet

from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


class SfcTestsCommonBase(test_base.DFTestBase):
    def _create_sf_port(self):
        port = self.subnet.create_port([])
        port.update({'device_id': 'device1'})
        return port

    @classmethod
    def _sf_callback(cls, buf):
        '''This is the code each SF runs, incs all chars in payload.
        '''

        pkt = ryu.lib.packet.packet.Packet(buf)
        protocols = pkt.protocols[:-1]
        payload = pkt.protocols[-1]

        new_payload = ''.join(chr(ord(c) + 1) for c in payload)

        new_pkt = ryu.lib.packet.packet.Packet()
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
        pp.create_from_ports(ingress, egress)

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

    def _gen_initial_packet(self, *_):
        res = ryu.lib.packet.packet.Packet()
        res.add_protocol(ryu.lib.packet.ethernet.ethernet(
            src=self.src_lport.get_mac(),
            dst=self.dst_lport.get_mac(),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        ))
        res.add_protocol(ryu.lib.packet.ipv4.ipv4(
            src=self.src_lport.get_ip(),
            dst=self.dst_lport.get_ip(),
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP,
        ))
        res.add_protocol(ryu.lib.packet.udp.udp(
            src_port=2222,
            dst_port=2222,
        ))

        res.add_protocol('asdf' * 15)
        res.serialize()
        return res.data

    def setUp(self):
        super(SfcTestsCommonBase, self).setUp()

        security_group = self.store(objects.SecGroupTestObj(
            self.neutron,
            self.nb_api))

        security_group_id = security_group.create()
        self.assertTrue(security_group.exists())

        for rule in (
            {
                'ethertype': 'IPv4',
                'direction': 'ingress',
                'protocol': 'udp',
                'port_range_min': 1,
                'port_range_max': 65535,
            },
            {
                'ethertype': 'IPv4',
                'direction': 'egress',
                'protocol': 'udp',
                'port_range_min': 1,
                'port_range_max': 65535,
            },
            {
                'ethertype': 'IPv4',
                'direction': 'ingress',
                'protocol': 'tcp',
                'port_range_min': 1,
                'port_range_max': 65535,
            },
            {
                'ethertype': 'IPv4',
                'direction': 'egress',
                'protocol': 'tcp',
                'port_range_min': 1,
                'port_range_max': 65535,
            },
        ):
            rule_id = security_group.rule_create(secrule=rule)
            self.assertTrue(security_group.rule_exists(rule_id))

        self.topology = self.store(
            app_testing_objects.Topology(
                self.neutron,
                self.nb_api,
            ),
        )

        self.subnet = self.topology.create_subnet('192.168.12.0/24')

        self.src_port = self.subnet.create_port([security_group_id])
        self.dst_port = self.subnet.create_port([security_group_id])

        self.src_port.update({
            'name': 'src_port',
            'admin_state_up': True,
            'fixed_ips': [
                {'subnet_id': self.subnet.subnet.subnet_id},
                {'subnet_id': self.subnet.subnet.subnet_id},
            ],
        })

        self.dst_port.update({
            'name': 'dst_port',
            'admin_state_up': True,
            'fixed_ips': [
                {'subnet_id': self.subnet.subnet.subnet_id},
                {'subnet_id': self.subnet.subnet.subnet_id},
            ],
        })

        self.src_lport = self.nb_api.get_logical_port(
            self.src_port.port.port_id)
        self.dst_lport = self.nb_api.get_logical_port(
            self.dst_port.port.port_id)

    def _create_port_policies(self, pc):
        res = {}
        for _, ppg in enumerate(pc.port_pair_groups):
            for _, pp in enumerate(ppg.port_pairs):
                key = (self.subnet.subnet_id, pp.ingress.port_id)
                res[key] = app_testing_objects.PortPolicy(
                    rules=[
                        app_testing_objects.PortPolicyRule(
                            app_testing_objects.RyuMplsFilter(),
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
        return ryu.lib.packet.ethernet.ethernet(
            src=(src or self.src_lport.get_mac()),
            dst=(dst or self.dst_lport.get_mac()),
            ethertype=(ethertype or ryu.lib.packet.ethernet.ether.ETH_TYPE_IP),
        )

    def _gen_ipv4(self, proto, src=None, dst=None):
        return ryu.lib.packet.ipv4.ipv4(
            src=(src or self.src_lport.get_ip()),
            dst=(dst or self.dst_lport.get_ip()),
            proto=proto,
        )

    def _gen_udp(self, src_port, dst_port):
        return ryu.lib.packet.udp.udp(
            src_port=src_port,
            dst_port=dst_port,
        )

    def _gen_tcp(self, src_port, dst_port, bits):
        return ryu.lib.packet.tcp.tcp(
            src_port=src_port,
            dst_port=dst_port,
            bits=bits,
        )

    def _get_bytes(self, pkt):
        pkt.serialize()
        return pkt.data


class TestFcApp(SfcTestsCommonBase):
    def _run_test(self, fc_params, chain_len, initial_packet, final_packet):
        fc = self.store(
            objects.FlowClassifierTestObj(self.neutron, self.nb_api),
        )
        fc.create(fc_params)
        pc = self._create_pc(fc, [1 for _ in range(chain_len)])
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

    def test_fc_on_source_port(self):
        self._run_test(
            fc_params={'logical_source_port': self.src_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_dest_port(self):
        self._run_test(
            fc_params={'logical_destination_port': self.dst_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_src_cidr(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'source_ip_prefix': str(
                    netaddr.IPNetwork(self.src_lport.get_ip()),
                ),
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_src_cidr_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'source_ip_prefix': str(
                    netaddr.IPNetwork(self.src_lport.get_ip_list()[1]),
                ),
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_dst_cidr(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'destination_ip_prefix': str(
                    netaddr.IPNetwork(self.dst_lport.get_ip()),
                ),
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_dst_cidr_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'destination_ip_prefix': str(
                    netaddr.IPNetwork(self.dst_lport.get_ip_list()[1]),
                ),
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_norange(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=2222,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=2222,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_norange_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_norange(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_norange_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=2222,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=2222,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_src_range(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
                'source_port_range_min': 2000,
                'source_port_range_max': 3000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_src_range_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
                'source_port_range_min': 1000,
                'source_port_range_max': 2000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_src_range(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
                'source_port_range_min': 2000,
                'source_port_range_max': 3000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_src_range_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
                'source_port_range_min': 1000,
                'source_port_range_max': 2000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_dst_range(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
                'destination_port_range_min': 4000,
                'destination_port_range_max': 5000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_tcp_dst_range_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'TCP',
                'destination_port_range_min': 1000,
                'destination_port_range_max': 2000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_TCP) /
                self._gen_tcp(
                    src_port=2222,
                    dst_port=4444,
                    bits=ryu.lib.packet.tcp.TCP_SYN,
                ) /
                ('0' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_dst_range(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
                'destination_port_range_min': 4000,
                'destination_port_range_max': 5000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('1' * 64)
            ),
            chain_len=1,
        )

    def test_fc_on_ipv4_udp_dst_range_negative(self):
        self._run_test(
            fc_params={
                'logical_destination_port': self.dst_port.port.port_id,
                'ethertype': 'IPv4',
                'protocol': 'UDP',
                'destination_port_range_min': 1000,
                'destination_port_range_max': 2000,
            },
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=4444) /
                ('0' * 64)
            ),
            chain_len=1,
        )


class TestSfcApp(SfcTestsCommonBase):
    def _run_test(self, fc_params, layout, initial_packet, final_packet):
        fc = self.store(
            objects.FlowClassifierTestObj(self.neutron, self.nb_api),
        )
        fc.create(fc_params)
        pc = self._create_pc(fc, layout)
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

    def test_single_ppg(self):
        self._run_test(
            fc_params={'logical_source_port': self.src_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            layout=[1],
        )

    def test_single_wide_ppg(self):
        self._run_test(
            fc_params={'logical_source_port': self.src_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('1' * 64)
            ),
            layout=[3],
        )

    def test_three_ppgs(self):
        self._run_test(
            fc_params={'logical_source_port': self.src_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('3' * 64)
            ),
            layout=[1, 1, 1],
        )

    def test_mixed_ppgs(self):
        self._run_test(
            fc_params={'logical_source_port': self.src_port.port.port_id},
            initial_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('0' * 64)
            ),
            final_packet=self._get_bytes(
                self._gen_ethernet() /
                self._gen_ipv4(proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP) /
                self._gen_udp(src_port=2222, dst_port=2222) /
                ('3' * 64)
            ),
            layout=[2, 1, 3],
        )
