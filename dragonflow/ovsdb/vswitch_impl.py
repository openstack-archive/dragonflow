# Copyright (c) 2015 OpenStack Foundation.
#
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

import netaddr
from oslo_config import cfg
from oslo_log import log
from ovs import vlog

from dragonflow.controller.common import constants
from dragonflow.db.models import ovs
from dragonflow.db.models import qos
from dragonflow.ovsdb import impl_idl

LOG = log.getLogger(__name__)

OFPORT_RANGE_MIN = 1
OFPORT_RANGE_MAX = 65533

OVS_LOG_FILE_NAME = 'df-ovs.log'


class OvsApi(object):
    """The interface of openvswitch

    Consumers use this class to set openvswitch or get results from
    openvswitch.
    """

    def __init__(self, ip, protocol='tcp', port='6640', timeout=10):
        super(OvsApi, self).__init__()
        self.ip = ip
        self.protocol = protocol
        self.port = port
        # NOTE: This has to be this name vsctl_timeout, as neutron will use
        # this attribute to set the timeout of ovs db.
        self.vsctl_timeout = timeout
        self.ovsdb = None
        self.integration_bridge = cfg.CONF.df.integration_bridge
        if cfg.CONF.log_dir:
            vlog.Vlog.init(cfg.CONF.log_dir + '/' + OVS_LOG_FILE_NAME)
        else:
            vlog.Vlog.init()

    def initialize(self, nb_api):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))

        nb_api.db_change_callback(None, None,
                                  constants.CONTROLLER_OVS_SYNC_STARTED, None)

        self.ovsdb = impl_idl.DFOvsdbApi(
            nb_api, db_connection, self.vsctl_timeout)

        nb_api.db_change_callback(None, None,
                                  constants.CONTROLLER_OVS_SYNC_FINISHED, None)

    def _db_get_val(self, table, record, column, check_error=False,
                    log_errors=True):
        return self.ovsdb.db_get(table, record, column).execute(
            check_error=check_error, log_errors=log_errors)

    def _get_bridge_for_iface(self, iface_name):
        return self.ovsdb.iface_to_br(iface_name).execute()

    def set_controller(self, bridge, targets):
        self.ovsdb.set_controller(bridge, targets).execute()

    def set_controller_fail_mode(self, bridge, fail_mode):
        self.ovsdb.set_fail_mode(bridge, fail_mode).execute()

    def check_controller(self, target):
        controllers = self.ovsdb.get_controller(
            self.integration_bridge).execute()
        return target in controllers

    def check_controller_fail_mode(self, fail_mode):
        return fail_mode == self._db_get_val('Bridge',
                                             self.integration_bridge,
                                             'fail_mode')

    def get_virtual_tunnel_ports(self):
        ifaces = self.ovsdb.db_find(
            'Interface', ('options', '=', {'remote_ip': 'flow'}),
            columns=['uuid', 'name', 'type']).execute()
        tunnel_ports = []
        for iface in ifaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(iface['name'])):
                continue

            tunnel_ports.append(
                ovs.OvsPort(
                    id=str(iface['uuid']),
                    name=iface['name'],
                    tunnel_type=iface['type'],
                ),
            )

        return tunnel_ports

    def add_virtual_tunnel_port(self, tunnel_type):
        self.ovsdb.add_virtual_tunnel_port(tunnel_type).execute()

    def delete_port(self, switch_port):
        self.ovsdb.del_port(switch_port.name,
                            self.integration_bridge).execute()

    @staticmethod
    def _check_ofport(port_name, ofport):
        if ofport is None:
            LOG.warning("Can't find ofport for port %s.", port_name)
            return False
        if ofport < OFPORT_RANGE_MIN or ofport > OFPORT_RANGE_MAX:
            LOG.warning("ofport %(ofport)s for port %(port)s is invalid.",
                        {'ofport': ofport, 'port': port_name})
            return False

        return True

    def get_interface_by_id_with_specified_columns(self, port_id,
                                                   specified_columns):
        columns = {'external_ids', 'name'}
        columns.update(specified_columns)
        ifaces = self.ovsdb.db_find(
            'Interface', ('external_ids', '=', {'iface-id': port_id}),
            columns=columns).execute()

        for iface in ifaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(iface['name'])):
                # iface-id is the port id in neutron, the same neutron port
                # might create multiple interfaces in different bridges
                continue
            return iface

    def get_port_ofport_by_id(self, port_id):
        iface = self.get_interface_by_id_with_specified_columns(
            port_id, {'name', 'ofport'})
        if iface and self._check_ofport(iface['name'], iface['ofport']):
            return iface['ofport']

    def get_local_port_mac_in_use(self, port_id):
        iface = self.get_interface_by_id_with_specified_columns(
            port_id, {'mac_in_use'})
        if iface and netaddr.valid_mac(iface['mac_in_use']):
            return iface['mac_in_use']

    def _get_port_name_by_id(self, port_id):
        ifaces = self.ovsdb.db_find(
            'Interface', ('external_ids', '=', {'iface-id': port_id}),
            columns=['external_ids', 'name']).execute()
        for iface in ifaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(iface['name'])):
                # iface-id is the port id in neutron, the same neutron port
                # might create multiple interfaces in different bridges
                continue

            return iface['name']

    def _gen_link_mapping(self, bridge1, bridge2,
                          bridge1_link_name=None,
                          bridge2_link_name=None):
        if bridge1_link_name is None:
            bridge1_link_name = "%s-patch" % bridge2
        if bridge2_link_name is None:
            bridge2_link_name = "%s-patch" % bridge1

        LOG.debug('genrated mappings {%(bridge1)s: %(link1)s,'
                  ' %(bridge2)s: %(link2)s}',
                  {'bridge1': bridge1,
                   'link1': bridge1_link_name,
                   'bridge2': bridge2,
                   'link2': bridge2_link_name})
        return (bridge1_link_name, bridge2_link_name)

    def map_patch_to_network(self, network, patch_name):
        self.bridge_mapping[network] = patch_name

    def get_phy_network_ofport(self, network):
        patch_name = self.bridge_mapping.get(network)
        if patch_name:
            return self.get_port_ofport(patch_name)

    def create_patch_pair(self, local_bridge, peer_bridge,
                          local_link_name=None, peer_link_name=None):
        links = self._gen_link_mapping(
                    local_bridge,
                    peer_bridge,
                    local_link_name,
                    peer_link_name)
        self._create_patch_port(
                    local_bridge,
                    links[0],
                    peer_bridge,
                    links[1])
        self._create_patch_port(
                    peer_bridge,
                    links[1],
                    local_bridge,
                    links[0])
        return links

    def _create_patch_port(self, bridge, port, peer, peer_port):
        if cfg.CONF.df.enable_dpdk:
            self.ovsdb.add_br(bridge, datapath_type='netdev').execute()
        else:
            self.ovsdb.add_br(bridge, datapath_type='system').execute()
        if not self.patch_port_exist(port):
            self.ovsdb.add_patch_port(bridge, port, peer, peer_port).execute()

    def patch_port_exist(self, port):
        return 'patch' == self._db_get_val('Interface', port, 'type',
                                           check_error=False,
                                           log_errors=False)

    def get_port_ofport(self, port):
        return self._db_get_val('Interface', port, 'ofport',
                                check_error=False, log_errors=False)

    def get_port_mac_in_use(self, port):
        return self._db_get_val('Interface', port, 'mac_in_use',
                                check_error=False, log_errors=False)

    def get_port_qos(self, port_id):
        port_qoses = self.ovsdb.db_find(
            'QoS', ('external_ids', '=', {'iface-id': port_id}),
            columns=['external_ids', '_uuid']).execute()
        if port_qoses:
            ovsdb_qos = port_qoses[0]
            external_ids = ovsdb_qos['external_ids']
            return qos.QosPolicy(
                id=external_ids.get('qos-id'),
                topic=external_ids.get('qos-topic'),
                version=external_ids.get('version'),
            )

    def set_port_qos(self, port_id, qos):
        port_name = self._get_port_name_by_id(port_id)
        if not port_name:
            return

        max_kbps = qos.get_max_kbps()
        max_burst_kbps = qos.get_max_burst_kbps()
        with self.ovsdb.transaction(check_error=True) as txn:
            qos_uuid = txn.add(self.ovsdb.create_qos(port_id, qos))
            txn.add(self.ovsdb.db_set('Interface', port_name,
                                      ('ingress_policing_rate', max_kbps),
                                      ('ingress_policing_burst',
                                       max_burst_kbps)))
            txn.add(self.ovsdb.db_set('Port', port_name, ('qos', qos_uuid)))

    def update_port_qos(self, port_id, qos):
        port_name = self._get_port_name_by_id(port_id)
        if not port_name:
            return

        max_kbps = qos.get_max_kbps()
        max_burst_kbps = qos.get_max_burst_kbps()
        with self.ovsdb.transaction(check_error=True) as txn:
            txn.add(self.ovsdb.db_set('Interface', port_name,
                                      ('ingress_policing_rate', max_kbps),
                                      ('ingress_policing_burst',
                                       max_burst_kbps)))
            txn.add(self.ovsdb.update_qos(port_id, qos))

    def clear_port_qos(self, port_id):
        port_name = self._get_port_name_by_id(port_id)
        if not port_name:
            return

        with self.ovsdb.transaction(check_error=True) as txn:
            txn.add(self.ovsdb.db_set('Interface', port_name,
                                      ('ingress_policing_rate', 0),
                                      ('ingress_policing_burst', 0)))
            txn.add(self.ovsdb.db_set('Port', port_name, ('qos', [])))
            txn.add(self.ovsdb.delete_qos(port_id))

    def delete_port_qos_and_queue(self, port_id):
        self.ovsdb.delete_qos(port_id).execute()

    def get_vtp_ofport(self, tunnel_type):
        return self.get_port_ofport(tunnel_type + '-vtp')
