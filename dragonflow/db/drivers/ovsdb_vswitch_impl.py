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
import ryu.contrib.ovs.json
from ryu.contrib.ovs.jsonrpc import Message

from dragonflow._i18n import _LE
from dragonflow.common import utils as df_utils
from dragonflow.db import api_vswitch

from neutron.agent.ovsdb import impl_idl
from neutron.agent.ovsdb.native.commands import BaseCommand
from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils

from oslo_log import log
import six
import socket
import time


LOG = log.getLogger(__name__)


class OvsdbSwitchApi(api_vswitch.SwitchApi):

    def __init__(self, ip, open_flow_app,
                 protocol='tcp', port='6640', timeout=10):
        super(OvsdbSwitchApi, self).__init__()
        self.ip = ip
        self.db_name = 'Open_vSwitch'
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self.ovsdb = None
        self.idl = None
        self.open_flow_app = open_flow_app

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = connection.Connection(db_connection,
                                           self.timeout,
                                           self.db_name)
        self.ovsdb.start()
        self.idl = self.ovsdb.idl

        ovsdb_monitor = OvsdbMonitor(self.ip, self.port, self.open_flow_app)
        ovsdb_monitor.daemonize()

    def transaction(self, check_error=False, log_errors=True, **kwargs):
        return impl_idl.Transaction(self,
                                    self.ovsdb,
                                    self.timeout,
                                    check_error, log_errors)

    def sync(self):
        self.idl.run()

    def del_controller(self, bridge):
        return DelControllerCommand(self, bridge)

    def set_controllers(self, bridge, targets):
        return SetControllerCommand(self, bridge, targets)

    def get_tunnel_ports(self):
        res = []
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                res.append(OvsdbTunnelPort(port, chassis_id))
        return res

    def add_tunnel_port(self, chassis):
        return AddTunnelPort(self, chassis)

    def delete_port(self, switch_port):
        return DeleteSwitchPort(self, switch_port)

    def get_local_port_ids(self):
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        port_ids = set()
        for port in br_int.ports:
            if port.name == 'br-int':
                continue
            if 'df-chassis-id' in port.external_ids:
                continue

            for interface in port.interfaces:
                if 'iface-id' in interface.external_ids:
                    port_ids.add(interface.external_ids['iface-id'])

        return port_ids

    def get_local_port_id_from_name(self, name):
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        for port in br_int.ports:
            if port.name != name:
                continue
            for interface in port.interfaces:
                if 'iface-id' in interface.external_ids:
                    return interface.external_ids['iface-id']

        return None

    def get_local_ports_to_ofport_mapping(self):
        lport_to_ofport = {}
        chassis_to_ofport = {}
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if port.name == 'br-int':
                continue
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


class OvsdbSwitchPort(api_vswitch.SwitchPort):

    def __init__(self, row):
        self.port_row = row

    def get_name(self):
        return self.port_row.name

    def get_id(self):
        pass


class OvsdbTunnelPort(OvsdbSwitchPort):

    def __init__(self, row, chassis_id):
        super(OvsdbTunnelPort, self).__init__(row)
        self.chassis_id = chassis_id

    def get_chassis_id(self):
        return self.chassis_id


class DelControllerCommand(BaseCommand):
    def __init__(self, api, bridge):
        super(DelControllerCommand, self).__init__(api)
        self.bridge = bridge

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        br.controller = []


class SetControllerCommand(BaseCommand):
    def __init__(self, api, bridge, targets):
        super(SetControllerCommand, self).__init__(api)
        self.bridge = bridge
        self.targets = targets

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        controllers = []
        for target in self.targets:
            controller = txn.insert(self.api.idl.tables['Controller'])
            controller.target = target
            controllers.append(controller)
        br.verify('controller')
        br.controller = controllers


class DeleteSwitchPort(BaseCommand):
    def __init__(self, api, switch_port):
        super(DeleteSwitchPort, self).__init__(api)
        self.switch_port = switch_port

    def run_idl(self, txn):
        port = self.switch_port.port_row
        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', 'br-int')
        bridge.verify('ports')
        ports = bridge.ports
        ports.remove(port)
        bridge.ports = ports

        # Remote Port Interfaces
        port.verify('interfaces')
        for iface in port.interfaces:
            self.api.idl.tables['Interface'].rows[iface.uuid].delete()

        self.api.idl.tables['Port'].rows[port.uuid].delete()


class AddTunnelPort(BaseCommand):
    def __init__(self, api, chassis):
        super(AddTunnelPort, self).__init__(api)
        self.chassis = chassis

    def run_idl(self, txn):
        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', 'br-int')
        port_name = "df-" + self.chassis.get_name()

        interface = txn.insert(self.api.idl.tables['Interface'])
        interface.name = port_name
        interface.type = self.chassis.get_encap_type()
        options_dict = getattr(interface, 'options', {})
        options_dict['remote_ip'] = self.chassis.get_ip()
        options_dict['key'] = 'flow'
        interface.options = options_dict

        port = txn.insert(self.api.idl.tables['Port'])
        port.name = port_name
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        ifaces.append(interface)
        port.interfaces = ifaces
        external_ids_dict = getattr(interface, 'external_ids', {})
        external_ids_dict['df-chassis-id'] = self.chassis.get_name()
        port.external_ids = external_ids_dict

        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports


class OvsdbMonitor(object):

    MONITOR_TABLE_NAME = "Interface"
    MSG_STATUS_NEW = "new"
    MSG_STATUS_OLD = "old"
    INTERFACE_FIELD_OFPORT = "ofport"
    INTERFACE_FIELD_NAME = "name"
    INTERFACE_FIELD_ADMIN_STATE = "admin_state"
    INTERFACE_FIELD_EXTERNAL_IDS = "external_ids"
    INTERFACE_FIELD_OPTIONS = "options"
    INTERFACE_FIELD_TYPE = "type"

    TYPE_UNKNOW_PORT = 0
    TYPE_VM_PORT = 1
    TYPE_TUNNEL_PORT = 2
    TYPE_BRIDGE_PORT = 3
    TYPE_PATCH_PORT = 4

    def __init__(self, ip, port, open_flow_app):
        super(OvsdbMonitor, self).__init__()
        self.ip = ip
        self.port = port
        self.input = ""
        self.output = ""
        self.parser = None
        self.sock = None
        self.monitor_request_id = None
        self.open_flow_app = open_flow_app
        self._daemon = df_utils.DFDaemon()

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def connect_ovsdb(self):
        address = (self.ip, int(self.port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)

        unconnected = True
        while unconnected:
            try:
                self.sock.connect(address)
                unconnected = False
            except socket.error as e:
                LOG.exception(_LE("could not connect to local ovsdb, %s"), e)
                time.sleep(5)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send_msg(self, msg):
        self.output += ryu.contrib.ovs.json.to_string(msg.to_json())
        try:
            while len(self.output):
                retval = self.sock.send(self.output)
                if retval > 0:
                    self.output = self.output[retval:]
                    continue
                elif retval == 0:
                    continue
                else:
                    break
        except socket.error as e:
            raise e

    def send_monitor_request(self):
        monitor_request = {}
        columns_keys = [OvsdbMonitor.INTERFACE_FIELD_OFPORT,
                        OvsdbMonitor.INTERFACE_FIELD_NAME,
                        OvsdbMonitor.INTERFACE_FIELD_ADMIN_STATE,
                        OvsdbMonitor.INTERFACE_FIELD_EXTERNAL_IDS,
                        OvsdbMonitor.INTERFACE_FIELD_OPTIONS,
                        OvsdbMonitor.INTERFACE_FIELD_TYPE]

        monitor_request[OvsdbMonitor.MONITOR_TABLE_NAME] = {
            "columns": columns_keys}
        msg = Message.create_request(
            "monitor", ["Open_vSwitch", None, monitor_request])
        self.monitor_request_id = msg.id
        try:
            self.send_msg(msg)
        except socket.error as e:
            raise e

    def handle_update(self, table_update):
        table_rows = table_update.get(OvsdbMonitor.MONITOR_TABLE_NAME)
        if table_rows is None:
            return

        for row_uuid, table_row in six.iteritems(table_rows):
            new = table_row.get(OvsdbMonitor.MSG_STATUS_NEW)
            old = table_row.get(OvsdbMonitor.MSG_STATUS_OLD)

            if not old and not new:
                return
            elif not new:
                # delete a old interface
                _interface = api_vswitch.LocalInterface()
                _interface.uuid = row_uuid
                self.parse_interface(_interface, old)
                self.open_flow_app.notify_remove_local_interface(_interface)
            else:
                # add a new interface or update a exist interface
                _interface = api_vswitch.LocalInterface()
                _interface.uuid = row_uuid
                self.parse_interface(_interface, new)
                self.open_flow_app.notify_add_local_interface(_interface)

    def judge_interface_type(self, input_dict):
        interface_type = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_TYPE)
        interface_name = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_NAME)

        if interface_type == "internal" and "br" in interface_name:
            return OvsdbMonitor.TYPE_BRIDGE_PORT

        if interface_type == "patch":
            return OvsdbMonitor.TYPE_PATCH_PORT

        external_ids = input_dict.get(
            OvsdbMonitor.INTERFACE_FIELD_EXTERNAL_IDS)
        external_elements = external_ids[1]
        for element in external_elements:
            if element[0] == "iface-id":
                return OvsdbMonitor.TYPE_VM_PORT

        options = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_OPTIONS)
        options_elements = options[1]
        for element in options_elements:
            if element[0] == "remote_ip":
                return OvsdbMonitor.TYPE_TUNNEL_PORT

        return OvsdbMonitor.TYPE_UNKNOW_PORT

    def parse_interface(self, _interface, input_dict):
        interface_type = self.judge_interface_type(input_dict)
        if interface_type == OvsdbMonitor.TYPE_UNKNOW_PORT:
            LOG.error(_LE("receive unknow interface:"), input_dict)
            return

        interface_ofport = input_dict.get(
            OvsdbMonitor.INTERFACE_FIELD_OFPORT)
        if isinstance(interface_ofport, list):
            _interface.ofport = -1
        else:
            _interface.ofport = interface_ofport

        interface_name = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_NAME)
        if isinstance(interface_name, list):
            _interface.name = ""
        else:
            _interface.name = interface_name

        interface_admin_state = input_dict.get(
            OvsdbMonitor.INTERFACE_FIELD_ADMIN_STATE)
        if isinstance(interface_admin_state, list):
            _interface.admin_state = ""
        else:
            _interface.admin_state = interface_admin_state

        if interface_type == OvsdbMonitor.TYPE_VM_PORT:
            _interface.type = "vm"
            external_ids = input_dict.get(
                OvsdbMonitor.INTERFACE_FIELD_EXTERNAL_IDS)
            external_elements = external_ids[1]
            for element in external_elements:
                if element[0] == "attached-mac":
                    _interface.attached_mac = element[1]
                elif element[0] == "iface-id":
                    _interface.iface_id = element[1]
        elif interface_type == OvsdbMonitor.TYPE_BRIDGE_PORT:
            _interface.type = "bridge"
        elif interface_type == OvsdbMonitor.TYPE_PATCH_PORT:
            _interface.type = "patch"
            options = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_OPTIONS)
            options_elements = options[1]
            for element in options_elements:
                if element[0] == "peer":
                    _interface.peer = element[1]
                    break
        elif interface_type == OvsdbMonitor.TYPE_TUNNEL_PORT:
            _interface.type = "tunnel"
            _interface.tunnel_type = input_dict.get(
                OvsdbMonitor.INTERFACE_FIELD_TYPE)
            options = input_dict.get(OvsdbMonitor.INTERFACE_FIELD_OPTIONS)
            options_elements = options[1]
            for element in options_elements:
                if element[0] == "remote_ip":
                    _interface.remote_ip = element[1]
                    break
        else:
            pass

    def wait_for_parser(self):
        while not self.parser.is_done():
            try:
                data = self.sock.recv(4095)
                if not data:
                    raise socket.error
                else:
                    self.input += data
            except socket.error as e:
                raise e
            self.input = self.input[self.parser.feed(self.input):]

    def handle_message(self):
        while True:
            self.parser = ryu.contrib.ovs.json.Parser()
            try:
                self.wait_for_parser()
            except socket.error as e:
                LOG.exception(_LE("exception happened "
                                  "when read from socket, %s"), e)
                return
            json_ = self.parser.finish()
            self.parser = None
            msg = Message.from_json(json_)
            if msg is None:
                continue
            elif msg.id == "echo":
                reply = Message.create_reply([], "echo")
                try:
                    self.send_msg(reply)
                except socket.error as e:
                    LOG.exception(_LE("exception happened "
                                      "when send msg, %s"), e)
                    return
            elif (msg.type == Message.T_NOTIFY
                  and msg.method == "update"
                  and len(msg.params) == 2
                  and msg.params[0] is None):
                self.handle_update(msg.params[1])
            elif (msg.type == Message.T_REPLY
                  and self.monitor_request_id is not None
                  and self.monitor_request_id == msg.id):
                self.monitor_request_id = None
                self.handle_update(msg.result)
            else:
                pass

    def run(self):
        while True:
            self.output = ""
            self.input = ""
            if self.sock is not None:
                self.sock.close()
                self.sock = None

            self.connect_ovsdb()
            try:
                self.send_monitor_request()
            except socket.error as e:
                LOG.exception(_LE("exception happened "
                                  "when send monitor request, %s"), e)
                continue

            self.handle_message()
