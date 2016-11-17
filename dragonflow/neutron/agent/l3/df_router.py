# Copyright (c) 2015 OpenStack Foundation.
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
#

from neutron.agent.l3 import agent
from neutron.agent.l3 import legacy_router


class DfDvrRouter(legacy_router.LegacyRouter):
    def add_floating_ip(self, fip, interface_name, device):
        if is_distributed_router(self.router):
            return
        return super(DfDvrRouter, self).add_floating_ip(
            fip, interface_name, device)

    def remove_floating_ip(self, device, ip_cidr):
        if is_distributed_router(self.router):
            return
        super(DfDvrRouter, self).remove_floating_ip(
            device, ip_cidr)

    def process_snat_dnat_for_fip(self):
        if is_distributed_router(self.router):
            return
        super(DfDvrRouter, self).process_snat_dnat_for_fip()


class DfL3NATAgentWithStateReport(agent.L3NATAgentWithStateReport):
    def __init__(self, host, conf=None):
        super(DfL3NATAgentWithStateReport, self).__init__(host=host, conf=conf)
        self.agent_state['binary'] = 'df-l3-agent'

    def _create_router(self, router_id, router):
        args = []
        kwargs = {
            'router_id': router_id,
            'router': router,
            'use_ipv6': self.use_ipv6,
            'agent_conf': self.conf,
            'interface_driver': self.driver,
        }

        if is_distributed_router(router):
            kwargs['agent'] = self
            kwargs['host'] = self.host
            return DfDvrRouter(*args, **kwargs)

        return super(DfL3NATAgentWithStateReport, self)._create_router(
            router_id, router)


def is_distributed_router(router):
    return router.get('distributed', False)
