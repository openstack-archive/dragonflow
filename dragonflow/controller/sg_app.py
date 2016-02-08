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

from dragonflow.controller.df_base_app import DFlowApp


class SGApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        # TODO(dingbo) local cache related to specific implementation

    def switch_features_handler(self, ev):
        # TODO(dingbo) restore SG related flow
        pass

    def remove_local_port(self, lport):

        # TODO(dingbo) remove SG related flow
        pass

    def remove_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_local_port(self, lport):

        # TODO(dingbo) add SG related flow
        pass

    def add_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_security_group_rule(self, secgroup, secgroup_rule):

        # TODO(dingbo) modify SG related flow
        pass

    def remove_security_group_rule(self, secgroup, secgroup_rule):

        # TODO(dingbo) modify SG related flow
        pass
