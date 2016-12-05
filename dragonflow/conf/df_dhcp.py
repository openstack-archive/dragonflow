# Copyright (c) 2015 Huawei Tech. Co., Ltd. .
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

df_dhcp_opts = [
    cfg.ListOpt('df_dns_servers',
        default=['8.8.8.8', '8.8.4.4'],
        help=_('Comma-separated list of the DNS servers which will be used.')),
    cfg.IntOpt('df_default_network_device_mtu', default=1460,
        help=_('default MTU setting for interface.')),
    cfg.IntOpt('df_dhcp_max_rate_per_sec', default=3,
        help=_('Port Max rate of DHCP messages per second')),
    cfg.IntOpt('df_dhcp_block_time_in_sec', default=100,
        help=_('Time to block port that passes the max rate')),
    cfg.BoolOpt('df_add_link_local_route', default=True,
        help=_("Set True to add route for link local address, which will be "
               "useful for metadata service.")),
]


def register_opts():
    cfg.CONF.register_opts(df_dhcp_opts, 'df_dhcp_app')


def list_opts():
    return {'df_dhcp_app': df_dhcp_opts}
