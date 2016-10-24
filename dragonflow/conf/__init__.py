#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from oslo_config import cfg

from dragonflow.conf import df_active_port_detection
from dragonflow.conf import df_cassandra
from dragonflow.conf import df_common_params
from dragonflow.conf import df_dhcp
from dragonflow.conf import df_dnat
from dragonflow.conf import df_l2
from dragonflow.conf import df_metadata_service
from dragonflow.conf import df_ryu


CONF = cfg.CONF


df_cassandra.register_opts()
df_common_params.register_opts()
df_dhcp.register_opts()
df_metadata_service.register_opts()
df_active_port_detection.register_opts()
df_l2.register_opts()
df_dnat.register_opts()
df_ryu.register_opts()
