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

    def logical_switch_deleted(self, lswitch):
        """logical switch deleted hook callback


        :param lswitch_id: logical switch id of the deleted switch
        """

    def logical_switch_updated(self, lswitch):
        """logical switch updated hook callback


        :param lswitch: logical switch that is updated
        """

    def router_updated(self, router, original_router):
        """router updated hook callback


        :param router: logical router that is updated
        :param original_router: logical router before update
        """

    def router_deleted(self, router):
        """router updated hook callback


        :param router: router that is deleted
        """
