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

df_opts = [
    cfg.StrOpt('remote_db_ip',
               default='127.0.0.1',
               help=_('The remote db server ip address')),
    cfg.IntOpt('remote_db_port',
               default=4001,
               help=_('The remote db server ip address')),
    cfg.StrOpt('nb_db_class',
               default='dragonflow.db.drivers.etcd_nb_impl.EtcdNbApi',
               help=_('The driver class for the NB DB')),
    cfg.StrOpt('local_ip',
               default='127.0.0.1',
               help=_('Local host IP')),
    cfg.StrOpt('tunnel_type',
               default='geneve',
               help=_('The encapsulation type for the tunnel')),
]
