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

from oslo_config import cfg

from dragonflow._i18n import _

df_dnat_app_opts = [
    cfg.StrOpt('external_network_bridge',
               default='br-ex',
               help=_("Name of bridge used for external network traffic")),
    cfg.StrOpt('int_peer_patch_port', default='patch-ex',
               help=_("Peer patch port in integration bridge for external "
                      "bridge.")),
    cfg.StrOpt('ex_peer_patch_port', default='patch-int',
               help=_("Peer patch port in external bridge for integration "
                      "bridge.")),
    cfg.IntOpt('dnat_ttl_invalid_max_rate', default=3,
               help=_('Max rate to reply ICMP time exceeded message per '
                      'second.')),
    cfg.IntOpt('dnat_icmp_error_max_rate', default=3,
               help=_('Max rate to handle ICMP error message per second.')),
]


def register_opts():
    cfg.CONF.register_opts(df_dnat_app_opts, group='df_dnat_app')


def list_opts():
    return {'df_dnat_app': df_dnat_app_opts}
