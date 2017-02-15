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


class CIDRList(object):
    """
    A class for saving a set of network addresses in CIDR list format.
    """
    def __init__(self):
        super(CIDRList, self).__init__()
        self._list = []

    @staticmethod
    def _if_cidrs_can_be_merged(cidr1, cidr2):
        if (cidr1.version == cidr2.version and
                cidr1.last + 1 == cidr2.first and
                cidr1.netmask == cidr2.netmask):
            netmask_int = int(cidr1.netmask)
            if netmask_int > 0:
                parent_netmask_int = (netmask_int & (netmask_int << 1))
                cidr1_parent_cidr = cidr1.network & parent_netmask_int
                cidr2_parent_cidr = cidr2.network & parent_netmask_int
                if cidr1_parent_cidr == cidr2_parent_cidr:
                    return True

        return False

    @staticmethod
    def _remove_one_address(cidr_list, address_to_remove):
        """cidr_list - IPNetwork list
           address_to_remove - IPAddress
        """
        added_cidr = []
        removed_cidr = []
        new_cidr_list = cidr_list

        for index in range(len(cidr_list)):
            cidr_item = cidr_list[index]
            if address_to_remove in cidr_item:
                removed_cidr = [cidr_item]
                added_cidr = netaddr.cidr_exclude(cidr_item, address_to_remove)

                new_cidr_list = cidr_list[:index]
                new_cidr_list.extend(added_cidr)
                new_cidr_list.extend(cidr_list[(index + 1):])
                break

        return new_cidr_list, added_cidr, removed_cidr

    @staticmethod
    def _add_one_address(cidr_list, address_to_add):
        """cidr_list - IPNetwork list
           address_to_add - IPAddress
        """
        position = None
        address_version = netaddr.IPAddress(address_to_add).version
        for index in range(len(cidr_list)):
            cidr_item = cidr_list[index]
            if cidr_item.version > address_version:
                position = index
                break
            if cidr_item.version < address_version:
                continue
            if cidr_item.last >= int(address_to_add):
                if cidr_item.first <= int(address_to_add):
                    return cidr_list, [], []
                position = index
                break

        if position is None:
            left_position = len(cidr_list) - 1
            right_position = len(cidr_list)
        else:
            left_position = position - 1
            right_position = position

        current_cidr = netaddr.IPNetwork(address_to_add)
        removed_cidr = []
        continue_flag = True
        while continue_flag:
            continue_flag = False
            if left_position >= 0:
                left_item = cidr_list[left_position]
                if CIDRList._if_cidrs_can_be_merged(left_item, current_cidr):
                    removed_cidr.append(left_item)
                    new_cidr_tuple = (left_item.first,
                                      left_item.prefixlen - 1)
                    current_cidr = netaddr.IPNetwork(new_cidr_tuple)
                    left_position -= 1
                    continue_flag = True
                    continue
            if right_position < len(cidr_list):
                right_item = cidr_list[right_position]
                if CIDRList._if_cidrs_can_be_merged(current_cidr, right_item):
                    removed_cidr.append(right_item)
                    new_cidr_tuple = (current_cidr.first,
                                      current_cidr.prefixlen - 1)
                    current_cidr = netaddr.IPNetwork(new_cidr_tuple)
                    right_position += 1
                    continue_flag = True
                    continue

        added_cidr = [current_cidr]
        new_cidr_list = cidr_list[:(left_position + 1)]
        new_cidr_list.extend(added_cidr)
        new_cidr_list.extend(cidr_list[right_position:])

        return new_cidr_list, added_cidr, removed_cidr

    def get_cidr_list(self):
        return self._list

    def clear(self):
        self._list = []

    def remove_addresses_and_get_changes(self, address_list):
        """address_list - IPAddress or string list
        """
        added_cidr = []
        removed_cidr = []
        new_cidr_list = self._list
        for removed_ip in address_list:
            new_cidr_list, temp_added_cidr, temp_removed_cidr = \
                self._remove_one_address(new_cidr_list,
                                         netaddr.IPAddress(removed_ip))
            added_cidr.extend(temp_added_cidr)
            removed_cidr.extend(temp_removed_cidr)

        filtered_added_cidr = \
            [cidr for cidr in added_cidr if cidr not in removed_cidr]
        filtered_removed_cidr = \
            [cidr for cidr in removed_cidr if cidr not in added_cidr]

        self._list = new_cidr_list
        return filtered_added_cidr, filtered_removed_cidr

    def add_addresses_and_get_changes(self, address_list):
        """address_list - IPAddress or string list
        """
        added_cidr = []
        removed_cidr = []
        new_cidr_list = self._list
        for added_ip in address_list:
            new_cidr_list, temp_added_cidr, temp_removed_cidr = \
                self._add_one_address(new_cidr_list,
                                      netaddr.IPAddress(added_ip))
            added_cidr.extend(temp_added_cidr)
            removed_cidr.extend(temp_removed_cidr)

        filtered_added_cidr = \
            [cidr for cidr in added_cidr if cidr not in removed_cidr]
        filtered_removed_cidr = \
            [cidr for cidr in removed_cidr if cidr not in added_cidr]

        self._list = new_cidr_list
        return filtered_added_cidr, filtered_removed_cidr

    def update_addresses_and_get_changes(self, addresses_to_add,
                                         addresses_to_remove):
        """addresses_to_add - IPAddress or string list
           addresses_to_remove - IPAddress or string list
        """
        added_cidr = []
        removed_cidr = []
        new_cidr_list = self._list
        for removed_ip in addresses_to_remove:
            new_cidr_list, temp_added_cidr, temp_removed_cidr = \
                self._remove_one_address(
                    new_cidr_list, netaddr.IPAddress(removed_ip)
                )
            added_cidr.extend(temp_added_cidr)
            removed_cidr.extend(temp_removed_cidr)

        for added_ip in addresses_to_add:
            new_cidr_list, temp_added_cidr, temp_removed_cidr = \
                self._add_one_address(
                    new_cidr_list, netaddr.IPAddress(added_ip)
                )
            added_cidr.extend(temp_added_cidr)
            removed_cidr.extend(temp_removed_cidr)

        filtered_added_cidr = \
            [cidr for cidr in added_cidr if cidr not in removed_cidr]
        filtered_removed_cidr = \
            [cidr for cidr in removed_cidr if cidr not in added_cidr]

        self._list = new_cidr_list
        return filtered_added_cidr, filtered_removed_cidr
