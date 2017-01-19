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

from neutron_lib.api.definitions import portbindings
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
               default='etcd_nb_db_driver',
               help=_('The driver to use for the NB database')),
    cfg.IPOpt('local_ip',
              default='127.0.0.1',
              help=_('Local host VTEP IP')),
    cfg.IPOpt('management_ip',
              default='127.0.0.1',
              help=_('Local host management IP')),
    cfg.StrOpt('tunnel_type',
               deprecated_for_removal=True,
               default='geneve',
               help=_('The encapsulation type for the tunnel')),
    cfg.ListOpt('tunnel_types',
                default=['geneve', 'vxlan', 'gre'],
                help=_("The encapsulation types for the tunnels")),
    cfg.BoolOpt('enable_dpdk',
                default=False,
                help=_("Enable dpdk")),
    cfg.StrOpt('apps_list',
               default='l2_app.L2App,'
                       'l3_proactive_app.L3ProactiveApp,'
                       'dhcp_app.DHCPApp',
               help=_('List of openflow applications classes to load')),
    cfg.StrOpt('integration_bridge', default='br-int',
               help=_("Integration bridge to use. "
                      "Do not change this parameter unless you have a good "
                      "reason to. This is the name of the OVS integration "
                      "bridge. There is one per hypervisor. The integration "
                      "bridge acts as a virtual 'patch bay'. All VM VIFs are "
                      "attached to this bridge and then 'patched' according "
                      "to their network connectivity.")),
    cfg.BoolOpt('use_centralized_ipv6_DHCP',
                default=False,
                help=_("Enable IPv6 DHCP by using DHCP agent")),
    cfg.BoolOpt('enable_df_pub_sub',
                default=False,
                help=_("Enable use of Dragonflow built-in pub/sub")),
    cfg.BoolOpt('enable_df_db_consistency',
                default=True,
                help=_("Enable use of Dragonflow db consistency")),
    cfg.StrOpt('pub_sub_driver',
               default='zmq_pubsub_driver',
               help=_('Drivers to use for the Dragonflow pub/sub')),
    cfg.StrOpt('pub_sub_multiproc_driver',
               default='zmq_pubsub_multiproc_driver',
               help=_('Drivers to use for the Dragonflow pub/sub')),
    cfg.BoolOpt('enable_port_status_notifier',
                default=False,
                help=_('Enable notifier for the Dragonflow port status')),
    cfg.StrOpt('port_status_notifier',
               default='redis_port_status_notifier_driver',
               help=_('Notifier for the Dragonflow port status')),
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
    cfg.IntOpt(
        'publisher_timeout',
        default=300,
        help=_('Publisher idle timeout before it is removed from the table')
    ),
    cfg.IntOpt(
        'db_sync_time',
        default=120,
        help=_('Min periodically db comparison time')
    ),
    cfg.IntOpt(
        'publisher_rate_limit_timeout',
        default=180,
        help=_(
            'Limit update of publishers\' table timestamp to '
            '$publisher_rate_limit_count per this many seconds.'
        )
    ),
    cfg.IntOpt(
        'publisher_rate_limit_count',
        default=1,
        help=_(
            'Limit update of publishers\' table timestamp to '
            'this many times per $publisher_rate_limit_timeout seconds.'
        )
    ),
    cfg.FloatOpt('monitor_table_poll_time',
                default=30,
                help=_('Poll monitored tables every this number of seconds')),
    cfg.BoolOpt('enable_selective_topology_distribution',
                default=False,
                help=_('When enabled, each controller will get only the part '
                       'of the topology relevant to it.')),
    cfg.StrOpt(
        'ovsdb_local_address',
        default='/usr/local/var/run/openvswitch/db.sock',
        help=_('local controller connect to the ovsdb server socket address')
    ),
    cfg.IntOpt('distributed_lock_ttl',
               default=120,
               help=_('The TTL of the distributed lock. The lock will be '
                      'reset if it is timeout.')),
    cfg.StrOpt("vif_type",
               default=portbindings.VIF_TYPE_OVS,
               help=_("Type of VIF to be used for ports valid values are"
                      "(%(ovs)s, %(vhostuser)s) default %(ovs)s") % {
                          "ovs": portbindings.VIF_TYPE_OVS,
                          "vhostuser": portbindings.VIF_TYPE_VHOST_USER},
               choices=[portbindings.VIF_TYPE_OVS,
                        portbindings.VIF_TYPE_VHOST_USER]),
    cfg.StrOpt("vhost_sock_dir",
               default="/var/run/openvswitch",
               help=_("The directory in which vhost virtio socket"
                      "is created by all the vswitch daemons")),
    cfg.StrOpt(
        'metadata_interface',
        default='tap-metadata',
        help=_('The name of the interface to bind the metadata service proxy'),
    )
]


def register_opts():
    cfg.CONF.register_opts(df_opts, 'df')


def list_opts():
    return {'df': df_opts}
