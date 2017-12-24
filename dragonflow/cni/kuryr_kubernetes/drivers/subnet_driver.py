# Copyright (c) 2017 OpenStack Foundation.
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

from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.db.models import l2

from kuryr_kubernetes.controller.drivers import base
from os_vif.objects import network as osv_network
from os_vif.objects import subnet as osv_subnet


class KuryrSubnetDriver(base.PodSubnetsDriver):

    def __init__(self):
        self.nb_api = None
        self.df_subnet = None
        self.df_lswitch = None
        self._init_nb_api()

    def _init_nb_api(self):
        # TODO(leyal) check initialize df_db in global scope
        df_utils.config_parse(args=["--config-file", "/etc/kuryr/kuryr.conf"])
        db_driver = df_utils.load_driver(cfg.CONF.df.nb_db_class,
                                         df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                             db_port=cfg.CONF.df.remote_db_port,
                             config=cfg.CONF.df)

        self.nb_api = api_nb.NbApi(db_driver, False)
        self._build_subnet()

    def _build_default_network(self):
        # TODO(leyal) build real network
        lswitch = l2.LogicalSwitch(
            id="POC_switch",
            topic="POC_topic",
            name="POC_switch_name",
            network_type="vxlan",
            segmentation_id=76,
            is_external='Internal',
            mtu=1450,
            version=1)

        return lswitch

    def _df_subnet_to_osvif_subnet(self, subnet):
        return osv_subnet.Subnet(
            cidr=subnet.cidr,
            dns=subnet.dns_nameservers,
            routes=subnet.host_routes)

    def _df_lswitch_to_osvif_network(self, lswitch):
        obj = osv_network.Network(id=lswitch.id)

        if lswitch.mtu is not None:
            obj.mtu = lswitch.mtu

        return obj

    def _build_subnet(self):
        # TODO(leyal) defualt subnet for POC read from config
        lswitch = self._build_default_network()
        subnet = l2.Subnet(
            id="POC_subnet",
            topic="POC_topic",
            name="POC_subnet_name",
            enable_dhcp=False,
            cidr="192.168.10.0/24",
            gateway_ip="192.168.100.1",
            dns_nameservers=[],
            host_routes=[]
        )

        lswitch.add_subnet(subnet)
        self.nb_api.create(lswitch)

        self.df_lswitch = lswitch
        self.df_subnet = subnet

    def get_subnets(self, pod, project_id):
        osvif_subnet = self._df_subnet_to_osvif_subnet(self.subnet)
        osvif_network = self._df_lswitch_to_osvif_network(self.lswitch)
        osvif_network.subnets.objects.append(osvif_subnet)
        return {self.subnet.id: osvif_network}
