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

from oslo_config import cfg
from oslo_log import log
from ovs import vlog

from dragonflow._i18n import _LW
from dragonflow.common import constants
from dragonflow.ovsdb import impl_idl
from dragonflow.ovsdb import objects

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
        self.ovsdb = impl_idl.DFOvsdbApi(
            self, nb_api, db_connection, self.vsctl_timeout)

        table = constants.OVS_INTERFACE
        nb_api.db_change_callback(table, None, 'sync_started', None)

        self.ovsdb.start()

        nb_api.db_change_callback(table, None, 'sync_finished', None)

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

    def get_tunnel_ports(self):
        res = []
        ports = self.ovsdb.get_bridge_ports(self.integration_bridge).execute()
        for port in ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                res.append(objects.OvsdbTunnelPort(port.name, chassis_id))
        return res

    def get_virtual_tunnel_ports(self):
        ifaces = self.ovsdb.db_find(
            'Interface', ('options', '=', {'remote_ip': 'flow'}),
            columns=['name', 'type']).execute()
        tunnel_ports = []
        for iface in ifaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(iface['name'])):
                continue

            tunnel_ports.append(objects.OvsdbVirtuaTunnelPort(iface['name'],
                                                              iface['type']))

        return tunnel_ports

    def add_tunnel_port(self, chassis):
        self.ovsdb.add_tunnel_port(chassis).execute()

    def add_virtual_tunnel_port(self, tunnel_type):
        self.ovsdb.add_virtual_tunnel_port(tunnel_type).execute()

    def delete_port(self, switch_port):
        self.ovsdb.del_port(switch_port.get_name(),
                            self.integration_bridge).execute()

    @staticmethod
    def _check_ofport(port_name, ofport):
        if ofport is None:
            LOG.warning(_LW("Can't find ofport for port %s."), port_name)
            return False
        if ofport < OFPORT_RANGE_MIN or ofport > OFPORT_RANGE_MAX:
            LOG.warning(_LW("ofport %(ofport)s for port %(port)s is invalid."),
                        {'ofport': ofport, 'port': port_name})
            return False

        return True

    def get_chassis_ofport(self, chassis_id):
        # TODO(xiaohhui): Can we just call get_port_ofport('df-'+chassis_id)?
        ports = self.ovsdb.db_find(
            'Port', ('external_ids', '=', {'df-chassis-id': chassis_id}),
            columns=['external_ids', 'name']).execute()
        for port in ports:
            ofport = self.get_port_ofport(port['name'])
            if self._check_ofport(port['name'], ofport):
                return ofport

    def get_port_ofport_by_id(self, port_id):
        ifaces = self.ovsdb.db_find(
            'Interface', ('external_ids', '=', {'iface-id': port_id}),
            columns=['external_ids', 'name', 'ofport']).execute()
        for iface in ifaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(iface['name'])):
                # iface-id is the port id in neutron, the same neutron port
                # might create multiple interfaces in different bridges
                continue
            if self._check_ofport(iface['name'], iface['ofport']):
                return iface['ofport']

    def create_patch_port(self, bridge, port, remote_name):
        self.ovsdb.add_br(bridge, datapath_type='system').execute()
        if not self.patch_port_exist(port):
            self.ovsdb.add_patch_port(bridge, port, remote_name).execute()
        return self.get_port_ofport(port)

    def patch_port_exist(self, port):
        return 'patch' == self._db_get_val('Interface', port, 'type',
                                           check_error=False,
                                           log_errors=False)

    def get_port_ofport(self, port):
        return self._db_get_val('Interface', port, 'ofport',
                                check_error=False, log_errors=False)
