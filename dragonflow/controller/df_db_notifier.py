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
import abc
import six


@six.add_metaclass(abc.ABCMeta)
class DBNotifyInterface(object):
    """An interface class which provide virtual hook callback functions stubs
    for an application wishing to be notified on db updates
    """

    @abc.abstractmethod
    def add_local_port(self, lport):
        """add local logical port hook callback


        :param lport:    local logical port which is added to db
        """

    @abc.abstractmethod
    def add_remote_port(self, lport):
        """add remote logical port hook callback


        :param lport:   logical port which resides on other compute node, and
        is added to db
        """

    @abc.abstractmethod
    def remove_local_port(self, lport_id):
        """remove local logical port hook callback


        :param lport_id:     id of local logical port that is removed from db
        """

    @abc.abstractmethod
    def remove_remote_port(self, lport_id):
        """remove remote logical port hook callback


        :param lport_id:      id of logical port which resides on other
        compute node, and is removed from db
        """

    @abc.abstractmethod
    def logical_switch_deleted(self, lswitch_id):
        """logical switch deleted hook callback


        :param lswitch_id: logical switch id of the deleted switch
        """

    @abc.abstractmethod
    def logical_switch_updated(self, lswitch):
        """logical switch updated hook callback


        :param lswitch: logical switch that is updated
        """
