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

import ryu.lib.packet
import sys
import time

from dragonflow._i18n import _LI
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.fullstack import test_base

from neutron.agent.common import utils

from oslo_log import log

LOG = log.getLogger(__name__)


class TestApps(test_base.DFTestBase):
    def test_infrastructure(self):
        try:
            topology = app_testing_objects.Topology(self.neutron, self.nb_api)
            subnet1 = topology.create_subnet(cidr='192.168.10.0/24')
            subnet2 = topology.create_subnet(cidr='192.168.11.0/24')
            port1 = subnet1.create_port()
            port2 = subnet2.create_port()
            topology.create_router([subnet1.subnet_id, subnet2.subnet_id])
            LOG.info(_LI('Port1 name: {}').format(port1.tap.tap.name))
            LOG.info(_LI('Port2 name: {}').format(port2.tap.tap.name))
            self._print_command(['ip', 'addr'])
            self._print_command(['ovs-vsctl', 'show'], True)
            self._print_command(['ovs-ofctl', 'show', 'br-int'], True)
            self._print_command(['ovs-ofctl', 'dump-flows', 'br-int'], True)
            self._print_command(['ovsdb-client', 'dump', 'Open_vSwitch'], True)
        except Exception as e:
            traceback = sys.exc_info()[2]
            try:
                topology.close()
            except Exception:
                pass  # Ignore
            # Just calling raise may raise an exception from topology.close()
            raise e, None, traceback
        topology.close()

    def _print_command(self, full_args, run_as_root=False):
            LOG.info(_LI('{}').format(utils.execute(
                full_args,
                run_as_root=run_as_root,
                process_input=None,
            )))


class TestArpResponder(test_base.DFTestBase):

    def setUp(self):
        super(TestArpResponder, self).setUp()
        self.topology = None
        self.policy = None
        try:
            self.topology = app_testing_objects.Topology(
                self.neutron,
                self.nb_api)
            subnet1 = self.topology.create_subnet(cidr='192.168.10.0/24')
            port1 = subnet1.create_port()
            port2 = subnet1.create_port()
            time.sleep(5)  # We need to wait for the tap devices to set up
            # Create policy
            arp_packet = self._create_arp_request(
                src_port=port1.port.get_logical_port(),
                dst_port=port2.port.get_logical_port(),
            )
            send_arp_request = app_testing_objects.SendAction(
                subnet1.subnet_id,
                port1.port_id,
                str(arp_packet),
            )
            ignore_action = app_testing_objects.IgnoreAction()
            log_action = app_testing_objects.LogAction()
            key1 = (subnet1.subnet_id, port1.port_id)
            port_policies = {
                key1: app_testing_objects.PortPolicy(
                    rules=[
                        app_testing_objects.PortPolicyRule(
                            # Detect arp replies
                            app_testing_objects.RyuARPReplyFilter(),
                            actions=[
                                log_action,
                                app_testing_objects.StopSimulationAction()
                            ]
                        ),
                        app_testing_objects.PortPolicyRule(
                            # Ignore IPv6 packets
                            app_testing_objects.RyuIPv6Filter(),
                            actions=[
                                ignore_action
                            ]
                        ),
                    ],
                    default_action=app_testing_objects.RaiseAction(
                        "Unexpected packet"
                    )
                ),
            }
            self.policy = app_testing_objects.Policy(
                initial_actions=[send_arp_request],
                port_policies=port_policies,
                unknown_port_action=ignore_action
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise
        self.store(self.topology)
        self.store(self.policy)

    def _create_arp_request(self, src_port, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=src_port.get_mac(),
            dst="ff:ff:ff:ff:ff:ff",
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_ARP,
        )
        arp = ryu.lib.packet.arp.arp_ip(
            opcode=1,
            src_mac=src_port.get_mac(), src_ip=src_port.get_ip(),
            dst_mac='00:00:00:00:00:00', dst_ip=dst_port.get_ip(),
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(arp)
        result.serialize()
        return result.data

    def tearDown(self):
        super(TestArpResponder, self).tearDown()
        self.policy.close()
        self.topology.close()

    def test_simple_response(self):
        """
        2 ports on 1 subnet. 1 port asks for MAC of other.
        Policy:
            port1:
                Send ARP request
                Receive ARP response
            port2:
                Do nothing
        """
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]
