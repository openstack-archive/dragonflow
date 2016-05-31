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


class DBNotifyInterface(object):
    """An interface class which provide virtual hook callback functions stubs
    for an application wishing to be notified on db updates
    """

    def add_local_port(self, lport):
        """add local logical port hook callback


        :param lport:    local logical port which is added to db
        """

    def update_local_port(self, lport, original_lport):
        """update local logical port hook callback

        :param lport:           local logical port which is updated to db
        :param original_lport:  local logical port in db before the update
        """

    def add_remote_port(self, lport):
        """add remote logical port hook callback


        :param lport:   logical port which resides on other compute node, and
        is added to db
        """

    def update_remote_port(self, lport, original_lport):
        """update remote logical port hook callback

        :param lport:           logical port which resides on other compute
        node, and is updated in db
        :param original_lport:  logical port in db which resides on other
        compute node before the update
        """

    def remove_local_port(self, lport):
        """remove local logical port hook callback


        :param lport: local logical port that is removed from db
        """

    def remove_remote_port(self, lport):
        """remove remote logical port hook callback


        :param lport:  logical port which resides on other
                       compute node, and is removed from db
        """

    def add_new_router_port(self, router, router_port, local_network_id):
        """add  new port to router hook callback


        param router:      the router that owns the new port
        param router_port: the new port
        param local_network_id: the id of the local network that the added port
        belongs to
        """

    def remove_router_port(self, router_port, local_network_id):
        """delete a  router port hook callback


        param router_port: the port to be deleted
        param local_network_id: the id of the local network that the port
        belongs to
        """

    def add_router_route(self, router, route):
        """add  new route to router callback
        param router: the router that the route to be added to
        param route:  the new route to be added
        """

    def remove_router_route(self, router, route):
        """delete route from a router callback
        param router: the router that the route to be deleted from
        param route:  the route to be deleted
        """

    def logical_switch_deleted(self, lswitch):
        """logical switch deleted hook callback


        :param lswitch_id: logical switch id of the deleted switch
        """

    def logical_switch_updated(self, lswitch):
        """logical switch updated hook callback


        :param lswitch: logical switch that is updated
        """
