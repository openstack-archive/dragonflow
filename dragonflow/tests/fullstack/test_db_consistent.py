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
from dragonflow.db.models import l2
from dragonflow.tests.common import constants
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


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
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
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
        self.assertIsNotNone(vm.server.addresses['mynetwork'])
        mac = vm.server.addresses['mynetwork'][0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)

        ovs = utils.OvsFlowsParser()
        utils.wait_until_true(
            lambda: self._check_l2_lookup_rule(
                    ovs.dump(self.integration_bridge), mac),
            timeout=10, sleep=1,
            exception=Exception('no rule for vm in l2 lookup table')
        )
        net_id = '11111111-1111-1111-1111-111111111111'
        df_network = l2.LogicalSwitch(
            id=net_id,
            topic=topic,
            name='df_nw1',
            network_type='vxlan',
            segmentation_id=4000,
            is_external=False,
            mtu=1500,
            unique_key=1,
            version=1)

        df_subnet = l2.Subnet(
            id='22222222-2222-2222-2222-222222222222',
            topic=topic,
            name='df_sn1',
            enable_dhcp=True,
            cidr='10.60.0.0/24',
            dhcp_ip='10.60.0.2',
            gateway_ip='10.60.0.1')

        df_network.add_subnet(df_subnet)
        df_network_json = df_network.to_json()

        self.nb_api.driver.create_key(
                'lswitch', net_id, df_network_json, topic)

        time.sleep(self.db_sync_time)
        utils.wait_until_true(
            lambda: utils.check_dhcp_ip_rule(
                    ovs.dump(self.integration_bridge), '10.60.0.2'),
            timeout=self.db_sync_time + constants.DEFAULT_CMD_TIMEOUT, sleep=1,
            exception=Exception('no goto dhcp rule for lswitch')
        )

        df_network.version = 2
        df_network.subnets[0].dhcp_ip = '10.60.0.3'
        df_network_json = df_network.to_json()
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
