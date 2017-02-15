# Copyright (c) 2017 OpenStack Foundation.
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

import netaddr
import random
import string

from dragonflow.controller.common import cidr_list
from dragonflow.tests import base as tests_base


class TestCIDRList(tests_base.BaseTestCase):

    def test_cidr_list(self):
        # initial aggregate addresses list
        aggreate_addresses = cidr_list.CIDRList()
        aggreate_addresses.add_addresses_and_get_changes(['192.168.10.6'])

        # add one address
        added_cidr, deleted_cidr = \
            aggreate_addresses.add_addresses_and_get_changes(['192.168.10.7'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.6/31')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.6/31')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # remove one address
        added_cidr, deleted_cidr = \
            aggreate_addresses.remove_addresses_and_get_changes(
                ['192.168.10.7'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.6/32')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/31')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # update addresses
        added_cidr, deleted_cidr = \
            aggreate_addresses.update_addresses_and_get_changes(
                ['192.168.10.7'], ['192.168.10.6'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.7/32')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.7/32')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # create lots of random IPv4 / IPv6 addresses
        lots_addreses = set()
        to_be_removed_addresses = set()
        to_be_removed_addresses2 = set()
        for loop1 in range(1, 6):
            for loop2 in range(0, 100):
                tail = str(random.randint(1, 254))
                address = '1.1.' + str(loop1) + '.' + tail
                lots_addreses.add(address)
                if loop2 < 10:
                    to_be_removed_addresses.add(address)
                elif loop2 < 20:
                    to_be_removed_addresses2.add(address)
        for loop1 in range(1, 3):
            for loop2 in range(0, 100):
                tail = ''.join(random.sample(string.hexdigits, 2))
                address = '::' + str(loop1) + ':' + tail.upper()
                lots_addreses.add(address)
                if loop2 < 10:
                    to_be_removed_addresses.add(address)
                elif loop2 < 20:
                    to_be_removed_addresses2.add(address)
        to_be_removed_addresses2 = (to_be_removed_addresses2 -
                                    to_be_removed_addresses)

        # compare cidr list after adding lots of IPv4 / IPv6 addresses
        aggreate_addresses = cidr_list.CIDRList()
        aggreate_addresses.add_addresses_and_get_changes(lots_addreses)
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in lots_addreses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())

        # compare cidr list after removing lots of IPv4 / IPv6 addresses
        aggreate_addresses.remove_addresses_and_get_changes(
            to_be_removed_addresses)
        new_lots_addresses = lots_addreses - to_be_removed_addresses
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in new_lots_addresses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())

        # compare cidr list after updating lots of IPv4 / IPv6 addresses
        aggreate_addresses.update_addresses_and_get_changes(
            to_be_removed_addresses, to_be_removed_addresses2)
        new_lots_addresses = lots_addreses - to_be_removed_addresses2
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in new_lots_addresses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())
