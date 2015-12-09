# Copyright (c) 2015 OpenStack Foundation.
#
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

from dragonflow.common import common_params
from neutron.common import config as common_config
from neutron.tests import base
from neutronclient.neutron import client
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import importutils

cfg.CONF.register_opts(common_params.df_opts, 'df')


class TestNeutronAPIandDB(base.BaseTestCase):

    def setUp(self):
        username = 'admin'
        password = 'devstack'
        auth_url = 'http://10.100.100.40:5000/v2.0'
        tenant_name = 'demo'
        #OS_URL = "http://10.100.100.40:5000/v2.0"
        #OS_TOKEN = "c5876bb22730477a8a190f5a6566a1b9"
        self.neutron = client.Client('2.0', username=username,
             password=password, auth_url=auth_url, tenant_name=tenant_name)
        self.neutron.format = 'json'
        common_config.init(['--config-file', '/etc/neutron/neutron.conf'])
        db_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.db_driver = db_driver_class()
        self.db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
            db_port=cfg.CONF.df.remote_db_port)

        super(TestNeutronAPIandDB, self).setUp()

    def test_create_network(self):
        # step1: create network
        test_network = 'mynetwork'
        network = {'name': test_network, 'admin_state_up': True}
        self.neutron.create_network({'network': network})
        # step2 : check if network created using neutron API
        networks = self.neutron.list_networks(name=test_network)
        if not networks or len(networks['networks']) == 0:
            self.fail("Failed to create network using neutron API")
        #print(networks)
        # step3: check if network created in dragonflow db
        table = 'lswitch'
        rows = self.db_driver.get_all_keys(table)
        good = 0
        for key in rows:
            value = self.db_driver.get_key(table, key)
            value2 = jsonutils.loads(value)
            if 'external_ids' in value2:
                if (value2['external_ids']['neutron:network_name'] ==
                        test_network):
                    #print('FOUND', key, value2)
                    # step4: delete network
                    self.neutron.delete_network(key)
                    good = 1
        if good == 0:
            self.fail("Failed to find newly created network in Dragonflow DB")
