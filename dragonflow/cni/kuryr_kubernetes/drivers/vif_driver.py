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

import six
import uuid

from oslo_log import log as logging

from kuryr.lib.binding.drivers import utils as binding_utils
from kuryr.lib import constants as kl_const
from kuryr_kubernetes.controller.drivers import base

from os_vif.objects import fixed_ip as osv_fixed_ip
from os_vif.objects import subnet as osv_subnet
from os_vif.objects import vif as osv_vif

from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.db.models import l2


LOG = logging.getLogger(__name__)


def _make_vif_subnets(df_port, subnets):

    # TODO(leyal) handle multiple ips
    ip = df_port.ip
    subnet_id = df_port.subnets[0].id
    network = subnets[subnet_id]
    subnet = network.subnets.objects[0].obj_clone()
    subnet.ips = osv_fixed_ip.FixedIPList(objects=[])
    subnet.ips.objects.append(osv_fixed_ip.FixedIP(address=ip))
    return [subnet]


def _make_vif_network(df_port, subnets):
    try:
        network = next(net.obj_clone() for net in subnets.values()
                       if net.id == df_port.lswitch.id)
    except StopIteration:
        raise ValueError(_("netwrok not found"))

    network.subnets = osv_subnet.SubnetList(
        objects=_make_vif_subnets(df_port, subnets))

    return network


class DFVifDriver(base.PodVIFDriver):

    def __init__(self):
        df_utils.config_parse(args=["--config-file", "/etc/kuryr/kuryr.conf"])
        db_driver = df_utils.load_driver(cfg.CONF.df.nb_db_class,
                                         df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                             db_port=cfg.CONF.df.remote_db_port,
                             config=cfg.CONF.df)

        self.nb_api = api_nb.NbApi(db_driver, False)
        self.addr_offset = 2

    def lport_to_vif_ovs(self, df_port, subnets):

        profile = osv_vif.VIFPortProfileOpenVSwitch(
            interface_id=df_port.id)

        ovs_bridge = 'br-int'

        network = _make_vif_network(df_port, subnets)
        network.bridge = ovs_bridge
        vif_name, _ = binding_utils.get_veth_pair_names(df_port.id)

        vif = osv_vif.VIFOpenVSwitch(
            id=df_port.id,
            address=str(df_port.mac),
            network=network,
            has_traffic_filtering=False,
            preserve_on_delete=False,
            # TODO(leyal) check port activeness
            active=True,
            port_profile=profile,
            plugin='ovs',
            vif_name=vif_name,
            bridge_name=network.bridge)
        return vif

    def _get_host_id(self, pod):
        return pod['spec']['nodeName']

    def get_ip_addr(self, osv_network):
        # TODO(leyal) a real ipam should be written
        subnet = osv_network.subnets.objects[0]
        net_addr = subnet.cidr.network
        ret = str(net_addr + self.addr_offset)
        self.addr_offset += 1
        return ret

    def _build_l2_port(self, ip_addr, topic,
                       subnet_id, security_groups, node_name):
        # TODO(leyal) find a way to pass network id from subnet driver
        return l2.LogicalPort(
            id=str(uuid.uuid4()),
            lswitch="POC_switch",
            topic=topic,
            macs=["aa:bb:cc:dd:ee:" + "{:02x}".format(self.addr_offset - 1)],
            ips=[ip_addr],
            subnets=[subnet_id],
            name="POC_PORT_{}".format((self.addr_offset - 1)),
            enabled=True,
            version=1,
            device_owner=kl_const.DEVICE_OWNER,
            security_groups=security_groups,
            port_security_enabled=False,
            allowed_address_pairs=[],
            binding=l2.PortBinding(type=l2.BINDING_CHASSIS,
                                   chassis=node_name),
        )

    def request_vif(self, pod, project_id, subnets, security_groups):
        # TODO(leyal) handle multiple subnet
        subnet_id, osv_network = six.next(six.iteritems(subnets))
        ip_addr = self.get_ip_addr(osv_network)
        lport = self._build_l2_port(ip_addr, project_id, subnet_id,
                                    security_groups,
                                    self._get_host_id(pod))
        self.nb_api.create(lport)
        vif = self.lport_to_vif_ovs(lport, subnets)
        return vif

    def release_vif(self, pod, vif, project_id=None, security_groups=None):
        # TODO(leyal) impelement
        pass

    def request_vifs(self, pod, project_id, subnets, security_groups,
                     num_ports):
        ret = []
        for x in range(0, num_ports):
            ret.append(self.request_vif(pod, project_id, subnets,
                                        security_groups))
        return ret

    def release_vifs(self, pod, vifs, project_id=None, security_groups=None):
        for vif in vifs:
            self.release_vif(pod, vif, project_id, security_groups)

    def activate_vif(self, pod, vif):
        pass
