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

df_opts = [
    cfg.IPOpt('remote_db_ip',
              default='127.0.0.1',
              help=_('The remote db server ip address')),
    cfg.PortOpt('remote_db_port',
                default=4001,
                help=_('The remote db server port')),
    cfg.ListOpt('remote_db_hosts',
                default=['$remote_db_ip:$remote_db_port'],
                help=_('Remote DB cluster host:port pairs.')),
    cfg.StrOpt('nb_db_class',
               default='dragonflow.db.drivers.etcd_db_driver.EtcdDbDriver',
               help=_('The driver class for the NB DB driver')),
    cfg.IPOpt('local_ip',
              default='127.0.0.1',
              help=_('Local host VTEP IP')),
    cfg.StrOpt('tunnel_type',
               default='geneve',
               help=_('The encapsulation type for the tunnel')),
    cfg.StrOpt('apps_list',
               default='l2_app.L2App,'
                       'l3_proactive_app.L3ProactiveApp,'
                       'dhcp_app.DHCPApp',
               help=_('List of openflow applications classes to load')),
    cfg.BoolOpt('use_centralized_ipv6_DHCP',
                default=False,
                help=_("Enable IPv6 DHCP by using DHCP agent")),
    cfg.BoolOpt('enable_df_pub_sub',
                default=False,
                help=_("Enable use of Dragonflow built-in pub/sub")),
    cfg.StrOpt('pub_sub_driver',
               default='zmq_pubsub_driver',
               help=_('Drivers to use for the Dragonflow pub/sub')),
    cfg.StrOpt('pub_sub_multiproc_driver',
               default='zmq_pubsub_multiproc_driver',
               help=_('Drivers to use for the Dragonflow pub/sub')),
    cfg.ListOpt('publishers_ips',
                default=['$local_ip'],
                help=_('List of the Neutron Server Publisher IPs.')),
    cfg.PortOpt('publisher_port',
                default=8866,
                help=_('Neutron Server Publishers port')),
    cfg.StrOpt('publisher_transport',
               default='tcp',
               help=_('Neutron Server Publishers transport protocol')),
    cfg.StrOpt('publisher_bind_address',
               default='*',
               help=_('Neutron Server Publishers bind address')),
    cfg.BoolOpt(
        'pub_sub_use_multiproc',
        default=True,
        help=_(
            'Use inter-process publish/subscribe. '
            'Publishers send events via the publisher service.'
        )
    ),
    cfg.StrOpt(
        'publisher_multiproc_socket',
        default='/var/run/zmq_pubsub/zmq-publisher-socket',
        help=_('Neutron Server Publisher inter-process socket address')
    ),
    cfg.FloatOpt('monitor_table_poll_time',
                default=30,
                help=_('Poll monitored tables every this number of seconds')),
]
