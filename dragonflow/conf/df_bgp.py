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


df_bgp_app_opts = [
    cfg.IntOpt(
        'pulse_interval',
        default=5,
        help=_('The interval of BGP service to get data updates and advertise '
               'BGP routes'))
]


def register_opts():
    cfg.CONF.register_opts(df_bgp_app_opts, group='df_bgp')


def list_opts():
    return {'df_bgp': df_bgp_app_opts}
