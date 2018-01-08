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
from dragonflow.db.models import l2
from dragonflow.tests import base
from dragonflow.tests.database import _dummy_db_driver


class TestIPAM(base.BaseTestCase):

    def setUp(self):
        super(TestIPAM, self).setUp()
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
        lean_ipam = l2.IPAM(id="subnet_id")
        ipam = nb_api.get(lean_ipam)
        self.assertTrue(ipam is not None)

        free_addrs = netaddr.IPSet(ipam.free_addrs)
        self.assertTrue("10.10.10.1" in free_addrs)
        self.assertFalse("10.10.10.0" in free_addrs)
        self.assertFalse("10.10.10.255" in free_addrs)
        self.assertEqual(ipam.cidr, netaddr.IPNetwork("10.10.10.0/24"))

    def test_ipam_get_addr(self):
        nb_api = api_nb.NbApi.get_instance(False)
        nb_api.create(l2.IPAM(
            id="subnet_id",
            cidr="10.10.10.0/24",
            free_addrs=["10.10.10.0/24"]
        ))
        ip = simple_ipam.request_ip(nb_api, "subnet_id")
        self.assertTrue(ip in netaddr.IPNetwork("10.10.10.0/24"))

    def test_remove_addr(self):
        nb_api = api_nb.NbApi.get_instance(False)
        nb_api.create(l2.IPAM(
            id="subnet_id",
            cidr="10.10.10.0/24",
            free_addrs=["10.10.10.128/25"]
        ))

        simple_ipam.release_ip(nb_api, "subnet_id", "10.10.10.1")
        ipam = nb_api.get(l2.IPAM(id="subnet_id"))
        ipset = netaddr.IPSet(ipam.free_addrs)
        self.assertTrue("10.10.10.1" in ipset)
        self.assertRaises(ValueError,
                          simple_ipam.release_ip,
                          nb_api, "subnet_id", "10.10.10.129")

        self.assertRaises(ValueError,
                          simple_ipam.release_ip, nb_api,
                          "subnet_id", "192.168.10.1")
