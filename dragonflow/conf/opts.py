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

from dragonflow.conf import df_common_params
from dragonflow.conf import df_dhcp
from dragonflow.conf import df_dnat
from dragonflow.conf import df_metadata_service
from dragonflow.conf import df_ryu
from dragonflow.conf import l2_ml2
from dragonflow.conf import router_distributed


def list_opts():
    return [
        ('df', df_common_params.df_opts),
        ('df_ryu', df_ryu.df_ryu_opts),
        ('df_dhcp_app', df_dhcp.df_dhcp_opts),
        ('df_dnat_app', df_dnat.df_dnat_app_opts),
        ('df_l2_app', l2_ml2.df_l2_app_opts),
        ('DEFAULT', router_distributed.router_distributed_opts),
        ('df_metadata', df_metadata_service.df_metadata_opts)]
