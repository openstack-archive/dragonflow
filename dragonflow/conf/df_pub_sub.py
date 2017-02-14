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


df_neutron_pub_sub_opts = [
    cfg.PortOpt('publisher_port',
                default=8866,
                help=_('Neutron Server Publishers port')),
    cfg.StrOpt('publisher_bind_address',
               default='*',
               help=_('Neutron Server Publishers bind address')),
    cfg.BoolOpt('pub_sub_use_multiproc',
                default=True,
                help=_('Use inter-process publish/subscribe. '
                       'Publishers send events via the publisher service.')),
    cfg.StrOpt('publisher_multiproc_socket',
               default='/var/run/zmq_pubsub/zmq-neutron-publisher-socket',
               help=_('Publisher inter-process socket address')),
    cfg.ListOpt('publishers_ips',
                default=['127.0.0.1'],
                help=_('List of the Publisher IPs.')),
]


df_ctrl_pub_sub_opts = [
    cfg.PortOpt('publisher_port',
                default=8867,
                help=_('Neutron Server Publishers port')),
    cfg.StrOpt('publisher_bind_address',
               default='*',
               help=_('Neutron Server Publishers bind address')),
    cfg.BoolOpt('pub_sub_use_multiproc',
                default=False,
                help=_('Use inter-process publish/subscribe. '
                       'Publishers send events via the publisher service.')),
    cfg.StrOpt('publisher_multiproc_socket',
               default='/var/run/zmq_pubsub/zmq-ctrl-publisher-socket',
               help=_('Publisher inter-process socket address')),
    cfg.ListOpt('publishers_ips',
                default=['127.0.0.1'],
                help=_('List of the Publisher IPs.')),
]


def register_opts():
    cfg.CONF.register_opts(df_neutron_pub_sub_opts, 'neutron')
    cfg.CONF.register_opts(df_ctrl_pub_sub_opts, 'controller')


def list_opts():
    return {'neutron': df_neutron_pub_sub_opts,
            'controller': df_ctrl_pub_sub_opts}
