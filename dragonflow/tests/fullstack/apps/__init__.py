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

CONTROLLER_RECONNECT_TIMEOUT = 10


def start_policy(policy, topology, timeout):
    policy.start(topology)
    policy.wait(timeout)

    if len(policy.exceptions) > 0:
        raise policy.exceptions[0]


def get_port_mac_and_ip(port, force_addr_pairs=False):
    port_lport = port.port.get_logical_port()
    allowed_address_pairs = port_lport.allowed_address_pairs
    if allowed_address_pairs:
        mac = allowed_address_pairs[0].mac_address
        ip = allowed_address_pairs[0].ip_address
    else:
        if force_addr_pairs:
            raise AssertionError(
                'allowed_address_pairs mandatory but empty')
        mac = port_lport.mac
        ip = port_lport.ip
    return mac, ip
