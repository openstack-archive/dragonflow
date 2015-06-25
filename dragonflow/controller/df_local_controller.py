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


import eventlet
import time

from ryu.base.app_manager import AppManager
from ryu.controller.ofp_handler import OFPHandler

from ovs.db import idl

from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils


from dragonflow.controller.l2_app import L2App

from oslo_log import log

LOG = log.getLogger(__name__)

eventlet.monkey_patch()


class DfLocalController(object):

    ovsdb_sb = connection.Connection('tcp:10.100.100.4:6640',
                                     10,
                                     'OVN_Southbound')
    ovsdb = connection.Connection('tcp:10.100.100.4:6640',
                                  10,
                                  'Open_vSwitch')

    def __init__(self):
        self.l3_app = None
        self.l2_app = None
        self.open_flow_app = None
        DfLocalController.ovsdb_sb.start()
        DfLocalController.ovsdb.start()
        self.next_network_id = 0
        self.networks = {}
        self.idl_sb = DfLocalController.ovsdb_sb.idl
        self.idl = DfLocalController.ovsdb.idl
        self.chassis_name = 'df_chassis'
        self.ip = '10.100.100.4'

    def run(self):
        app_mgr = AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(OFPHandler, None, None)
        self.open_flow_app.start()
        self.l2_app = app_mgr.instantiate(L2App, None, None)
        self.l2_app.start()
        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(3)
            self.run_db_poll()

    def run_db_poll(self):
        try:
            self.idl.run()
            self.idl_sb.run()
            #self.clean_tables()

            self.register_chassis()

            self.create_tunnels()

            self.set_binding()

            self.port_mappings()
        except Exception:
            pass

    def clean_tables(self):
        txn = idl.Transaction(self.idl_sb)
        for chassis in self.idl_sb.tables['Chassis'].rows.values():
            chassis.delete()
        for encap in self.idl_sb.tables['Encap'].rows.values():
            encap.delete()
        for binding in self.idl_sb.tables['Binding'].rows.values():
            binding.delete()
        status = txn.commit_block()
        return status

    def register_chassis(self):

        try:
            chassis = idlutils.row_by_value(self.idl_sb,
                                            'Chassis',
                                            'name', self.chassis_name)
            if chassis is not None:
                # TODO(gsagie) Support tunnel type change here ?
                return
        except idlutils.RowNotFound:
            txn = idl.Transaction(self.idl_sb)

            encap_row = txn.insert(self.idl_sb.tables['Encap'])
            encap_row.ip = self.ip
            encap_row.type = 'geneve'

            chassis_row = txn.insert(self.idl_sb.tables['Chassis'])
            chassis_row.encaps = encap_row
            chassis_row.name = self.chassis_name
            status = txn.commit_block()
            return status

    def create_tunnels(self):
        tunnel_ports = {}
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                tunnel_ports[chassis_id] = port

        for chassis in self.idl_sb.tables['Chassis'].rows.values():
            if chassis.name in tunnel_ports:
                # Chassis already set
                del tunnel_ports[chassis.name]
            elif chassis.name == self.chassis_name:
                pass
            else:
                encap = chassis.encaps[0]
                self.tunnel_add(br_int, chassis, encap)

        # Iterate all tunnel ports that needs to be deleted
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        for port in tunnel_ports.values():
            self.delete_bridge_port(br_int, port)

    def tunnel_add(self, bridge, chassis, encap):
        txn = idl.Transaction(self.idl)
        port_name = "df-" + chassis.name

        interface = txn.insert(self.idl.tables['Interface'])
        interface.name = port_name
        interface.type = encap.type
        options_dict = getattr(interface, 'options', {})
        options_dict['remote_ip'] = encap.ip
        options_dict['key'] = 'flow'
        interface.options = options_dict

        port = txn.insert(self.idl.tables['Port'])
        port.name = port_name
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        ifaces.append(interface)
        port.interfaces = ifaces
        external_ids_dict = getattr(interface, 'external_ids', {})
        external_ids_dict['df-chassis-id'] = chassis.name
        port.external_ids = external_ids_dict

        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports

        status = txn.commit_block()
        return status

    def delete_bridge_port(self, bridge, port):
        txn = idl.Transaction(self.idl)
        bridge.verify('ports')
        ports = bridge.ports
        ports.remove(port)
        bridge.ports = ports

        # Remote Port Interfaces
        port.verify('interfaces')
        for iface in port.interfaces:
            self.idl.tables['Interface'].rows[iface.uuid].delete()

        self.idl.tables['Port'].rows[port.uuid].delete()

        status = txn.commit_block()
        return status

    def set_binding(self):
        local_ports = self.get_local_ports()
        txn = idl.Transaction(self.idl_sb)

        chassis = idlutils.row_by_value(self.idl_sb,
                                        'Chassis',
                                        'name', self.chassis_name)

        for binding in self.idl_sb.tables['Binding'].rows.values():
            if binding.logical_port in local_ports:
                if binding.chassis == self.chassis_name:
                    continue
                # Bind this port to this chassis
                binding.chassis = chassis
            elif binding.chassis == self.chassis_name:
                binding.chassis = []

        status = txn.commit_block()
        return status

    def port_mappings(self):
        lport_to_ofport = {}
        chassis_to_ofport = {}
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if port.name == 'br-int':
                continue
            chassis_id = port.external_ids.get('df-chassis-id')
            if chassis_id is not None and chassis_id == self.chassis_name:
                continue
            for interface in port.interfaces:
                if interface.ofport is None:
                    continue
                ofport = interface.ofport[0]
                if ofport < 1 or ofport > 65533:
                    continue
                if chassis_id is not None:
                    chassis_to_ofport[chassis_id] = ofport
                else:
                    ifaceid = interface.external_ids.get('iface-id')
                    if ifaceid is not None:
                        lport_to_ofport[ifaceid] = ofport

        for binding in self.idl_sb.tables['Binding'].rows.values():
            if not binding.chassis:
                continue
            logical_port = binding.logical_port
            mac_address = binding.mac[0]
            chassis = binding.chassis[0]
            ldp = str(binding.logical_datapath)
            network = self.get_network_id(ldp)
            tunnel_key = binding.tunnel_key
            if chassis.name == self.chassis_name:
                ofport = lport_to_ofport.get(logical_port, 0)
                if ofport != 0:
                    self.l2_app.add_local_port(logical_port,
                                               mac_address,
                                               network,
                                               ofport,
                                               tunnel_key)
            else:
                ofport = chassis_to_ofport.get(chassis.name, 0)
                if ofport != 0:
                    self.l2_app.add_remote_port(logical_port,
                                                mac_address,
                                                network,
                                                ofport,
                                                tunnel_key)

    def get_network_id(self, logical_dp_id):
        network_id = self.networks.get(logical_dp_id)
        if network_id is not None:
            return network_id
        else:
            self.next_network_id += 1
            # TODO(gsagie) verify self.next_network_id didnt wrap
            self.networks[logical_dp_id] = self.next_network_id

    def get_local_ports(self):
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


def main():
    controller = DfLocalController()
    controller.run()

if __name__ == "__main__":
    main()
