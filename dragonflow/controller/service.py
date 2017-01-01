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

import socket

from dragonflow.common import report_status
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import api_nb


class Service(object):
    def __init__(self, binary):
        nb_driver = df_utils.load_driver(
            cfg.CONF.df.nb_db_class,
            df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.nb_api = api_nb.NbApi(
            nb_driver,
            use_pubsub=cfg.CONF.df.enable_df_pub_sub)

        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

        chassis = socket.gethostname()
        self.nb_api.create_service(chassis, binary)
        report_status.run_status_reporter(self.nb_api.report_up,
                                          self.nb_api,
                                          chassis,
                                          binary)
