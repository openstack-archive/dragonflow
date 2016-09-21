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

from dragonflow.common.common_params import DF_OPTS
from dragonflow.controller.df_local_controller import DF_RYU_OPTS
from dragonflow.controller.dhcp_app import DF_DHCP_OPTS
from dragonflow.controller.dnat_app import DF_DNAT_APP_OPTS
from dragonflow.controller.l2_ml2_app import DF_L2_APP_OPTS
from dragonflow.controller.metadata_service_app import DF_METADATA_OPTS


CONF = cfg.CONF


def list_opts():
    return [
        ('df', DF_OPTS),
        ('df_ryu', DF_RYU_OPTS),
        ('df_dhcp_app', DF_DHCP_OPTS),
        ('df_dnat_app', DF_DNAT_APP_OPTS),
        ('df_l2_app', DF_L2_APP_OPTS),
        ('df_metadata', DF_METADATA_OPTS)]
