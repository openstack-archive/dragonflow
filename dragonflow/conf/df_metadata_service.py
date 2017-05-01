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


df_metadata_opts = [
    cfg.IPOpt(
        'ip',
        default='169.254.169.254',
        help=_('The IP to which the DF metadata service proxy is bound'),
    ),
    cfg.PortOpt(
        'port',
        default='18080',
        help=_('The port to which the DF metadata service proxy is bound'),
    ),
    cfg.StrOpt(
        'metadata_interface',
        default='tap-metadata',
        help=_('The name of the interface to bind the metadata'
               'service proxy'))
]


def register_opts():
    cfg.CONF.register_opts(df_metadata_opts, group='df_metadata')


def list_opts():
    return {'df_metadata': df_metadata_opts}
