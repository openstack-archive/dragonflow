# Copyright (c) 2017 Huawei Tech. Co., Ltd. .
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

df_l3_app_opts = [
    cfg.IntOpt('router_ttl_invalid_max_rate', default=3,
               help=_('Max rate to reply ICMP time exceeded message per '
                      'second.')),
    cfg.IntOpt('router_port_unreach_max_rate', default=3,
               help=_('Max rate to reply ICMP unreachable message per '
                      'second for router port.')),
]


def register_opts():
    cfg.CONF.register_opts(df_l3_app_opts, group='df_l3_app')


def list_opts():
    return {'df_l3_app': df_l3_app_opts}
