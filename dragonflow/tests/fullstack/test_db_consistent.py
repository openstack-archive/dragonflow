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

import time

from dragonflow.controller.common import constants as const
from dragonflow.db import db_consistent
from dragonflow.db import models
from dragonflow.tests.common import constants
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

from oslo_serialization import jsonutils


class TestDbConsistent(test_base.DFTestBase):

    def _check_l2_lookup_rule(self, flows, mac):
        goto_egress = 'goto_table:' + str(const.EGRESS_TABLE)
        for flow in flows:
            if (flow['table'] == str(const.L2_LOOKUP_TABLE)
                and goto_egress in flow['actions']):
                if 'dl_dst=' + mac in flow['match']:
                    return True
        return False

    def _check_no_lswitch_dhcp_rule(self, flows, dhcp_ip):
        if utils.check_dhcp_ip_rule(flows, dhcp_ip):
            return False
        return True

    def test_db_consistent(self):
        self.db_sync_time = self.conf.db_sync_time
        if self.db_sync_time < db_consistent.MIN_SYNC_INTERVAL_TIME:
            self.db_sync_time = db_consistent.MIN_SYNC_INTERVAL_TIME
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
        topic = network.get_topic()
        subnet = self.store(objects.SubnetTestObj(self.neutron, self.nb_api,
                                                  network_id))
        subnet_body = {'network_id': network_id,
            'cidr': '10.50.0.0/24',
            'gateway_ip': '10.50.0.1',
            'ip_version': 4,
            'name': 'private',
            'enable_dhcp': True}
        subnet.create(subnet=subnet_body)
        time.sleep(constants.DEFAULT_RESOURCE_READY_TIMEOUT)
        self.assertTrue(network.exists())
        self.assertTrue(subnet.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        self.assertIsNotNone(vm.server.addresses['private'])
        mac = vm.server.addresses['private'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)

        ovs = utils.OvsFlowsParser()
        utils.wait_until_true(
            lambda: self._check_l2_lookup_rule(
                    ovs.dump(self.integration_bridge), mac),
            timeout=10, sleep=1,
            exception=Exception('no rule for vm in l2 lookup table')
        )
        df_network = {}
        net_id = '11111111-1111-1111-1111-111111111111'
        df_network['id'] = net_id
        df_network['topic'] = topic
        df_network['name'] = 'df_nw1'
        df_network['network_type'] = 'vxlan'
        df_network['segmentation_id'] = 4000
        df_network['router_external'] = False
        df_network['mtu'] = 1500
        df_network[models.UNIQUE_KEY] = 1
        df_network['version'] = 1

        df_subnet = {}
        df_subnet['id'] = '22222222-2222-2222-2222-222222222222'
        df_subnet['lswitch'] = net_id
        df_subnet['name'] = 'df_sn1'
        df_subnet['enable_dhcp'] = True
        df_subnet['cidr'] = '10.60.0.0/24'
        df_subnet['dhcp_ip'] = '10.60.0.2'
        df_subnet['gateway_ip'] = '10.60.0.1'
        df_subnet['dns_nameservers'] = []
        df_subnet['host_routes'] = []

        df_network['subnets'] = [df_subnet]
        df_network_json = jsonutils.dumps(df_network)

        self.nb_api.driver.create_key(
                'lswitch', net_id, df_network_json, topic)

        time.sleep(self.db_sync_time)
        utils.wait_until_true(
            lambda: utils.check_dhcp_ip_rule(
                    ovs.dump(self.integration_bridge), '10.60.0.2'),
            timeout=self.db_sync_time + constants.DEFAULT_CMD_TIMEOUT, sleep=1,
            exception=Exception('no goto dhcp rule for lswitch')
        )

        df_network['version'] = 2
        df_network['subnets'][0]['dhcp_ip'] = '10.60.0.3'
        df_network_json = jsonutils.dumps(df_network)
        self.nb_api.driver.set_key('lswitch', net_id, df_network_json, topic)

        time.sleep(self.db_sync_time)
        utils.wait_until_true(
            lambda: utils.check_dhcp_ip_rule(
                    ovs.dump(self.integration_bridge), '10.60.0.3'),
            timeout=self.db_sync_time + constants.DEFAULT_CMD_TIMEOUT, sleep=1,
            exception=Exception('no goto dhcp rule for lswitch')
        )

        self.nb_api.driver.delete_key('lswitch', net_id, topic)
        time.sleep(self.db_sync_time)
        utils.wait_until_true(
            lambda: self._check_no_lswitch_dhcp_rule(
                    ovs.dump(self.integration_bridge), '10.60.0.3'),
            timeout=self.db_sync_time + constants.DEFAULT_CMD_TIMEOUT, sleep=1,
            exception=Exception('could not delete goto dhcp rule for lswitch')
        )

        vm.close()
        subnet.close()
        network.close()
