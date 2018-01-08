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

import mock
import netaddr

from oslo_config import cfg

from dragonflow.cni import simple_ipam
from dragonflow.common import utils as df_utils
from dragonflow.db import api_nb
from dragonflow.db.models import ipam
from dragonflow.db.models import l2
from dragonflow.tests import base
from dragonflow.tests.database import _dummy_db_driver


class TestIPAM(base.BaseTestCase):

    def setUp(self):
        super(TestIPAM, self).setUp()
        api_nb._nb_api = None
        db_driver = _dummy_db_driver._DummyDbDriver()
        cfg.CONF.df.enable_df_pub_sub = False
        driver_mock = mock.patch.object(df_utils, 'load_driver',
                                        return_value=db_driver)
        driver_mock.start()
        self.addCleanup(driver_mock.stop)

    def test_ipam_create(self):
        nb_api = api_nb.NbApi.get_instance(False)
        nb_api.create(l2.Subnet(id="subnet_id",
                                cidr="10.10.10.0/24",
                                topic="test"))
        simple_ipam.add_subnet_ipam(nb_api, "subnet_id")
        lean_ipam = ipam.IPAM(id="subnet_id")
        ipam_obj = nb_api.get(lean_ipam)

        free_addrs = netaddr.IPSet(ipam_obj.free_addrs)
        self.assertTrue("10.10.10.1" in free_addrs)
        self.assertFalse("10.10.10.0" in free_addrs)
        self.assertFalse("10.10.10.255" in free_addrs)
        self.assertEqual(ipam_obj.cidr, netaddr.IPNetwork("10.10.10.0/24"))

    def test_ipam_get_addr(self):
        nb_api = api_nb.NbApi.get_instance(False)
        ipam_obj = ipam.IPAM(
            id="subnet_id",
            cidr="10.10.10.0/30",
            free_addrs=["10.10.10.1/32", "10.10.10.2/32"]
        )
        nb_api.create(ipam_obj)
        self.addCleanup(nb_api.delete, ipam_obj)

        # Simulate creation of 3 ips from range that have 2 valid ips
        # check that 2 created successfully and on failed.
        ips = []
        for i in range(0, 3):
            ips.insert(i, simple_ipam.request_ip(nb_api, "subnet_id"))

        self.assertTrue(netaddr.IPAddress("10.10.10.1") in ips)
        self.assertTrue(netaddr.IPAddress("10.10.10.2") in ips)
        self.assertTrue(ips[2] is None)

    def test_remove_addr(self):
        nb_api = api_nb.NbApi.get_instance(False)
        nb_api.create(ipam.IPAM(
            id="subnet_id",
            cidr="10.10.10.0/24",
            free_addrs=["10.10.10.128/25"]
        ))

        # Simulate client that release valid ip that previously allocated
        simple_ipam.release_ip(nb_api, "subnet_id", "10.10.10.1")
        ipam_obj = nb_api.get(ipam.IPAM(id="subnet_id"))
        ipset = netaddr.IPSet(ipam_obj.free_addrs)

        # Simulate Client that release it's ip twice
        self.assertTrue("10.10.10.1" in ipset)
        self.assertRaises(ValueError,
                          simple_ipam.release_ip,
                          nb_api, "subnet_id", "10.10.10.129")

        # Simulate client that release an not valid ips
        self.assertRaises(ValueError,
                          simple_ipam.release_ip, nb_api,
                          "subnet_id", "192.168.10.1")
