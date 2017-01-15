# Copyright (c) 2016 OpenStack Foundation.
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

from oslo_config import cfg

from dragonflow._i18n import _


df_l2_app_opts = [
    cfg.BoolOpt(
        'l2_responder',
        default=True,
        help=_('Install OVS flows to respond to ARP and ND requests.')),
    cfg.ListOpt('bridge_mappings',
                default=[],
                help=_("Comma-separated list of <physical_network>:<bridge> "
                       "tuples mapping physical network names to the "
                       "dragonflow's node-specific Open vSwitch bridge names "
                       "to be used for flat and VLAN networks. Each bridge "
                       "must exist, and should have a physical network "
                       "interface configured as a port. All physical "
                       "networks configured on the server should have "
                       "mappings to appropriate bridges on each dragonflow "
                       "node.")),
]


def register_opts():
    cfg.CONF.register_opts(df_l2_app_opts, group='df_l2_app')


def list_opts():
    return {'df_l2_app': df_l2_app_opts}
