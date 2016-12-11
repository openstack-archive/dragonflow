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
from ryu.ofproto import ofproto_common

from dragonflow._i18n import _

df_ryu_opts = [
    cfg.IPOpt('of_listen_address', default='127.0.0.1',
              help=_("Address to listen on for OpenFlow connections.")),
    cfg.PortOpt('of_listen_port', default=ofproto_common.OFP_TCP_PORT,
                help=_("Port to listen on for OpenFlow connections."))
]


def register_opts():
    cfg.CONF.register_opts(df_ryu_opts, 'df_ryu')


def list_opts():
    return {'df_ryu': df_ryu_opts}
