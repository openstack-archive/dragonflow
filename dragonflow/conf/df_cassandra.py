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


df_cassandra_opts = [
    cfg.StrOpt(
        'consistency_level',
        default='one',
        help=_('The default consistency level for Cassandra session.'
               'The value should be any, one, two, three, quorum, all,'
               'local_quorum, each_quorum, serial, local_serial, local_one.'),
    ),
    cfg.StrOpt(
        'load_balancing',
        default='rr',
        help=_('The default load balancing policy for Cassandra cluster.'
               'The value should be rr, dc_rr, wl_rr, token_rr.'),
    ),
    cfg.StrOpt(
        'local_dc_name',
        default='local',
        help=_('The DC name for dc_rr load balancing policy.'),
    ),
    cfg.IntOpt(
        'used_hosts_per_remote_dc',
        default=0,
        help=_('The number of respected remote hosts for '
               'dc_rr load balancing policy.'),
    ),
    cfg.StrOpt(
        'whitelist_hosts',
        default='localhost',
        help=_('The hosts to permit connections to for wl_rr load balancing '
               'policy. Please specify a list of hosts by comma.'),
    ),
]


def register_opts():
    cfg.CONF.register_opts(df_cassandra_opts, group='df_cassandra')


def list_opts():
    return {'df_cassandra': df_cassandra_opts}
