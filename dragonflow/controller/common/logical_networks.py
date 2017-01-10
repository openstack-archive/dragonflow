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

import collections
import functools


class LogicalNetworks(object):
    """
    LogicalNetworks is a common infra class that cache local and remote
    ports according to their network id and network_type.
    The internal data structure can  be represnted as
    {location:{network_id:{network_type:<port list>}}}
    """
    def __init__(self):
        initializer = functools.partial(collections.defaultdict, list)
        self.local_ports_net_cache = collections.defaultdict(initializer)
        self.remote_ports_net_cache = collections.defaultdict(initializer)

    def _add_port(self, ports, port_id, network_id, network_type):
        network_ports = ports[network_id]
        network_ports[network_type].append(port_id)

    def _remove_port(self, ports, port_id, network_id, network_type):
        network_ports = ports.get(network_id)
        if network_ports:
            if port_id in network_ports[network_type]:
                network_ports[network_type].remove(port_id)

    def _get_port_count(self, ports, network_id, network_type):
        value = 0
        network_ports = ports.get(network_id)
        if network_ports:
            if network_type:
                value = len(network_ports[network_type])
            else:
                for port_list in network_ports.values():
                    value += len(port_list)
        return value

    def _get_ports(self, ports, network_id, network_type):
        network_ports = ports.get(network_id)
        if network_ports:
            if network_type:
                return network_ports[network_type]
            else:
                ret_list = list()
                for port_list in network_ports.values():
                    ret_list += port_list
                return ret_list
        return None

    def add_local_port(self, port_id, network_id, network_type):
        """add local (on this compute host) logical port"""
        return self._add_port(ports=self.local_ports_net_cache,
                              port_id=port_id,
                              network_id=network_id,
                              network_type=network_type)

    def add_remote_port(self, port_id, network_id, network_type):
        """add remote (on other compute host) logical port"""
        return self._add_port(ports=self.remote_ports_net_cache,
                              port_id=port_id,
                              network_id=network_id,
                              network_type=network_type)

    def remove_local_port(self, port_id, network_id, network_type):
        """remove local logical port entry"""
        return self._remove_port(ports=self.local_ports_net_cache,
                                 port_id=port_id,
                                 network_id=network_id,
                                 network_type=network_type)

    def remove_remote_port(self, port_id, network_id, network_type):
        """remove remote logical port entry"""
        return self._remove_port(ports=self.remote_ports_net_cache,
                                 port_id=port_id,
                                 network_id=network_id,
                                 network_type=network_type)

    def get_local_port_count(self, network_id, network_type=None):
        """count of local ports belong to network  identified by
           network_id, if type specified,  it will count only
           ports according to type, otherwise all  ports are counted
        """
        return self._get_port_count(ports=self.local_ports_net_cache,
                                    network_id=network_id,
                                    network_type=network_type)

    def get_remote_port_count(self, network_id, network_type=None):
        """count of remote ports belong to network  identified by
           network_id, if type specified,  it will count only
           ports according to type, otherwise all  ports are counted
        """
        return self._get_port_count(ports=self.remote_ports_net_cache,
                                    network_id=network_id,
                                    network_type=network_type)

    def get_local_ports(self, network_id, network_type=None):
        """get all id's of local ports belong to network  identified by
           network_id, if type specified,  it will fetch only
           ports according to type, otherwise all  ports are assembled
        """
        return self._get_ports(ports=self.local_ports_net_cache,
                               network_id=network_id,
                               network_type=network_type)

    def get_remote_ports(self, network_id, network_type=None):
        """get all id's of remote ports belong to network  identified by
           network_id, if type specified,  it will fetch only
           ports according to type, otherwise all  ports are assembled
        """
        return self._get_ports(ports=self.remote_ports_net_cache,
                               network_id=network_id,
                               network_type=network_type)
