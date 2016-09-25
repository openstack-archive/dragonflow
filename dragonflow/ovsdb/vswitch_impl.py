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
from ovs import vlog

from dragonflow.common import constants
from dragonflow.ovsdb import impl_idl
from dragonflow.ovsdb import objects


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
        vlog.Vlog.init('dragonflow')

    def initialize(self, nb_api):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = impl_idl.DFOvsdbApi(
            self, db_connection, self.vsctl_timeout)

        table = constants.OVS_INTERFACE
        nb_api.db_change_callback(table, None, 'sync_started', None)

        self.ovsdb.start(nb_api)

        nb_api.db_change_callback(table, None, 'sync_finished', None)

    def _db_get_val(self, table, record, column, check_error=False,
                    log_errors=True):
        return self.ovsdb.db_get(table, record, column).execute(
            check_error=check_error, log_errors=log_errors)

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
                res.append(objects.OvsdbTunnelPort(chassis_id))
        return res

    def add_tunnel_port(self, chassis):
        self.ovsdb.add_tunnel_port(chassis).execute()

    def delete_port(self, switch_port):
        self.ovsdb.del_port(switch_port.get_name(),
                            self.integration_bridge).execute()

    def get_local_ports_to_ofport_mapping(self):
        lport_to_ofport = {}
        chassis_to_ofport = {}
        ports = self.ovsdb.get_bridge_ports(self.integration_bridge).execute()
        for port in ports:
            chassis_id = port.external_ids.get('df-chassis-id')
            for interface in port.interfaces:
                if interface.ofport is None:
                    # TODO(gsagie) log error
                    continue
                ofport = interface.ofport[0]
                if ofport < 1 or ofport > 65533:
                    # TODO(gsagie) log error
                    continue
                if chassis_id is not None:
                    chassis_to_ofport[chassis_id] = ofport
                else:
                    ifaceid = interface.external_ids.get('iface-id')
                    if ifaceid is not None:
                        lport_to_ofport[ifaceid] = ofport

        return chassis_to_ofport, lport_to_ofport

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
