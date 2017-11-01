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


df_skydive_app_opts = [
    cfg.StrOpt('analyzer_endpoint',
               default='127.0.0.1:8082',
               help=_('IP:Port of skydive analyzer.')),
    cfg.StrOpt('user',
               default='admin',
               help=_('Username to authenticate to the skydive analyzer.')),
    cfg.StrOpt('password',
               help=_('password to authenticate to the skydive analyzer.'))
]


def register_opts():
    cfg.CONF.register_opts(df_skydive_app_opts, group='df_skydive')


def list_opts():
    return {'df_skydive': df_skydive_app_opts}
