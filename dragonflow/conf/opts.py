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

from dragonflow.common import common_params
from dragonflow.conf import metadata_service_app
from dragonflow.controller import df_local_controller
from dragonflow.controller import dhcp_app
from dragonflow.controller import dnat_app
from dragonflow.controller import l2_ml2_app


CONF = cfg.CONF


def list_opts():
    metadata_service_app.register_opts()
    return [
        ('df', common_params.DF_OPTS),
        ('df_ryu', df_local_controller.DF_RYU_OPTS),
        ('df_dhcp_app', dhcp_app.DF_DHCP_OPTS),
        ('df_dnat_app', dnat_app.DF_DNAT_APP_OPTS),
        ('df_l2_app', l2_ml2_app.DF_L2_APP_OPTS),
        ('df_metadata', metadata_service_app.DF_METADATA_OPTS)]
