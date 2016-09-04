# Copyright (c) 2015 OpenStack Foundation.
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
import random


class BloomFilter(object):
    def __init__(self, num_bytes, num_probes, iterable=()):
        """Bloom filter implementation

        Example: Check if number in set

        >>> bf = BloomFilter(8, 2, (123, 321, 213, 3123))
        >>> 123 in bf
        True
        >>> 456 in bf
        False

        :param num_bytes: Number of bytes in the filter
        :type num_bytes: int
        :param num_probes: Number of bloom filter probes
        :type num_probes: int
        :param iterable: Iterable set of items to create the filter from
        """
        self._array = bytearray(num_bytes)
        self._num_probes = num_probes
        self._num_bits = num_bytes * 8
        self.update(iterable)

    @property
    def array(self):
        return self._array

    def _get_probes(self, key):
        rdm = random.Random(key).random
        return (int(rdm() * self._num_bits)
                for _probe in range(self._num_probes))

    def update(self, keys):
        """Add keys to the current filter
        :param keys: iterable set of keys
        """
        for key in keys:
            for i in self._get_probes(key):
                self._array[i // 8] |= 2 ** (i % 8)

    def __contains__(self, key):
        return all(self._array[i // 8] & (2 ** (i % 8))
                   for i in self._get_probes(key))
