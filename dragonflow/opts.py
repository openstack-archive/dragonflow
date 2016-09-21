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

import copy
import itertools
import operator

from oslo_config import cfg

import dragonflow.common.common_params
import dragonflow.controller.df_local_controller
import dragonflow.controller.dhcp_app
import dragonflow.controller.dnat_app
import dragonflow.controller.l2_ml2_app
import dragonflow.controller.metadata_service_app


CONF = cfg.CONF

def list_opts():
    return [
        ('df', common_params.df_opts),
        ('df_ryu', df_local_controller.df_ryu_opts),
        ('df_dhcp_app', dhcp_app.DF_DHCP_OPTS),
        ('df_dnat_app', dnat_app.DF_DNAT_APP_OPTS),
        ('df_l2_app', l2_ml2_app.DF_L2_APP_OPTS),
        ('df_metadata', metadata_service_app.options)]
