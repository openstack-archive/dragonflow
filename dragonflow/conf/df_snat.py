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

from oslo_config import cfg

from dragonflow._i18n import _

df_snat_app_opts = [
    cfg.BoolOpt('enable_goto_flows',
                default=True,
                help=_("Enable install of common goto flows to ingress/egress "
                       "NAT tables or re-use goto flows installed by "
                       "other DF application")),
    cfg.StrOpt('external_network_bridge',
               default='br-ex',
               help=_("Name of bridge used for external network traffic")),
]


def register_opts():
    cfg.CONF.register_opts(df_snat_app_opts, group='df_snat_app')


def list_opts():
    return {'df_snat_app': df_snat_app_opts}
