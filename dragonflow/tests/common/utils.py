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

from neutron.agent.common import utils
from neutron.agent.linux.utils import wait_until_true
import re


#: It takes some time from the moment the command is sent to Neutron, until it
#: propagates down to the DF controller and DF DB. It shouldn't be more than,
#: say, 2 seconds.
DEFAULT_CMD_TIMEOUT = 30


def wait_until_is_and_return(predicate, timeout=5, sleep=1, exception=None):
    container = {}

    def internal_predicate():
        container['value'] = predicate()
        return container['value']

    wait_until_true(internal_predicate, timeout, sleep, exception)
    return container.get('value')


def wait_until_none(predicate, timeout=5, sleep=1, exception=None):
    def internal_predicate():
        ret = predicate()
        if ret:
            return False
        return True
    wait_until_true(internal_predicate, timeout, sleep, exception)


def print_command(full_args, run_as_root=False):
    print '{}'.format(utils.execute(
        full_args,
        run_as_root=run_as_root,
        process_input=None,
    ))


class OvsFlowsParser(object):

    def get_ovs_flows(self, integration_bridge):
        full_args = ["ovs-ofctl", "dump-flows", integration_bridge,
                     "-O Openflow13"]
        flows = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return flows

    def _parse_ovs_flows(self, flows):
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            if len(flow) == 0:
                continue
            if 'OFPST_FLOW' in flow:
                continue
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1].replace(',', '')
            res['match'] = fs[-2]
            res['actions'] = fs[-1].split('=')[1]
            res['cookie'] = fs[1].split('=')[1].replace(',', '')
            m = re.search('priority=(\d+)', res['match'])
            if m:
                res['priority'] = m.group(1)
                res['match'] = re.sub(r'priority=(\d+),?', '', res['match'])
            flows_as_dicts.append(res)
        return flows_as_dicts

    def diff_flows(self, list1, list2):
        result = [v for v in list2 if v not in list1]
        return result

    def dump(self, integration_bridge):
        flows = self.get_ovs_flows(integration_bridge)
        return self._parse_ovs_flows(flows)


class OvsDBParser(object):

    def _ovsdb_list_intefaces(self, specify_interface=None):
        full_args = ["ovs-vsctl", "list", 'interface']
        if specify_interface:
            full_args.append(specify_interface)
        interfaces_info = utils.execute(full_args, run_as_root=True,
                                        process_input=None)
        return interfaces_info

    def _trim_double_quotation(self, value):
        if len(value) != 0 and value[0] == '\"':
            return value[1:-1]
        return value

    def _parse_one_item(self, str_item):
        value = None
        start_index = str_item.find(': ')
        if start_index != -1:
            value = str_item[start_index + 2:]
            if value[0] == '[':
                items_str = value[1:-1]
                value = []
                if len(items_str) != 0:
                    items = items_str.split(', ')
                    for loop in items:
                        value.append(self._trim_double_quotation(loop))
            elif value[0] == '{':
                items_str = value[1:-1]
                value = {}
                if len(items_str) != 0:
                    items = items_str.split(', ')
                    for loop in items:
                        key_value = loop.split('=')
                        value[key_value[0]] = \
                            self._trim_double_quotation(key_value[1])
            else:
                value = self._trim_double_quotation(value)
        return value

    def _parse_ovsdb_interfaces(self, interfaces):
        interfaces_list = interfaces.split("\n\n")
        interfaces_as_dicts = []
        for inteface in interfaces_list:
            if len(inteface) == 0:
                continue
            fs = inteface.split("\n")
            res = {}
            for item in fs:
                if item.startswith('external_ids'):
                    res['external_ids'] = self._parse_one_item(item)
                elif item.startswith('ofport '):
                    res['ofport'] = self._parse_one_item(item)
                elif item.startswith('name'):
                    res['name'] = self._parse_one_item(item)
            interfaces_as_dicts.append(res)
        return interfaces_as_dicts

    def list_interfaces(self, specify_interface=None):
        interfaces = self._ovsdb_list_intefaces(specify_interface)
        return self._parse_ovsdb_interfaces(interfaces)

    def get_ofport(self, port_id):
        interfaces = self.list_interfaces()
        for item in interfaces:
            external_ids = item.get('external_ids', None)
            if external_ids is not None:
                iface_id = external_ids.get('iface-id', None)
                if iface_id == port_id:
                    return item.get('ofport', None)
        return None

    def get_port_id_by_vm_id(self, vm_id):
        interfaces = self.list_interfaces()
        for item in interfaces:
            external_ids = item.get('external_ids', None)
            if external_ids is not None:
                temp_vm_id = external_ids.get('vm-id', None)
                if temp_vm_id == vm_id:
                    return external_ids.get('iface-id', None)
        return None

    def _ovsdb_list_ports(self, specify_port=None):
        full_args = ["ovs-vsctl", "list", "port"]
        if specify_port:
            full_args.append(specify_port)
        ports_info = utils.execute(full_args, run_as_root=True,
                                   process_input=None)
        return ports_info

    def _parse_ovsdb_ports(self, ports):
        ports_list = ports.split("\n\n")
        ports_as_dicts = []
        for port in ports_list:
            if len(port) == 0:
                continue
            fs = port.split("\n")
            res = {}
            for item in fs:
                if item.startswith('qos'):
                    res['qos'] = self._parse_one_item(item)
                if item.startswith('interfaces'):
                    res['interfaces'] = self._parse_one_item(item)
            ports_as_dicts.append(res)
        return ports_as_dicts

    def _ovsdb_list_qoss(self, qos=None):
        full_args = ["ovs-vsctl", "list", "qos"]
        if qos:
            full_args.append(qos)
        qoss_info = utils.execute(full_args, run_as_root=True,
                                  process_input=None)
        return qoss_info

    def _parse_ovsdb_qoss(self, qoss):
        qoss_list = qoss.split("\n\n")
        qoss_as_dicts = []
        for qos in qoss_list:
            if len(qos) == 0:
                continue
            fs = qos.split("\n")
            res = {}
            for item in fs:
                if item.startswith('external_ids'):
                    res['external_ids'] = self._parse_one_item(item)
                if item.startswith('queues'):
                    res['queues'] = self._parse_one_item(item)
                if item.startswith('_uuid'):
                    res['_uuid'] = self._parse_one_item(item)
            qoss_as_dicts.append(res)
        return qoss_as_dicts

    def _ovsdb_list_queues(self, queue=None):
        full_args = ["ovs-vsctl", "list", "queue"]
        if queue:
            full_args.append(queue)
        queues_info = utils.execute(full_args, run_as_root=True,
                                    process_input=None)
        return queues_info

    def _parse_ovsdb_queues(self, queues):
        queues_list = queues.split("\n\n")
        queues_as_dicts = []
        for queue in queues_list:
            if len(queue) == 0:
                continue
            fs = queue.split("\n")
            res = {}
            for item in fs:
                if item.startswith('_uuid'):
                    res['_uuid'] = self._parse_one_item(item)
                if item.startswith('dscp'):
                    res['dscp'] = self._parse_one_item(item)
                if item.startswith('other_config'):
                    res['other_config'] = self._parse_one_item(item)
                if item.startswith('external_ids'):
                    res['external_ids'] = self._parse_one_item(item)
            queues_as_dicts.append(res)
        return queues_as_dicts

    def get_port_by_interface_id(self, interface_id):
        ports_info = self._ovsdb_list_ports()
        ports_as_dict_list = self._parse_ovsdb_ports(ports_info)
        for item in ports_as_dict_list:
            interfaces = item.get('interfaces', None)
            if interfaces is not None:
                temp_interface_id = interfaces[0]
                if temp_interface_id == interface_id:
                    return item
        return None

    def get_interface_by_port_id(self, port_id):
        interfaces = self.list_interfaces()
        for item in interfaces:
            external_ids = item.get('external_ids', None)
            if external_ids is not None:
                iface_id = external_ids.get('iface-id', None)
                if iface_id == port_id:
                    return item
        return None

    def get_qos_by_port_id(self, port_id):
        qoss_info = self._ovsdb_list_qoss()
        qoss_as_dict_list = self._parse_ovsdb_qoss(qoss_info)
        for item in qoss_as_dict_list:
            external_ids = item.get('external_ids', None)
            if external_ids is not None:
                iface_id = external_ids.get('iface-id', None)
                if iface_id == port_id:
                    return item
        return None

    def get_queue_by_port_id(self, port_id):
        queues_info = self._ovsdb_list_queues()
        queues_as_dict_list = self._parse_ovsdb_queues(queues_info)
        for item in queues_as_dict_list:
            external_ids = item.get('external_ids', None)
            if external_ids is not None:
                iface_id = external_ids.get('iface-id', None)
                if iface_id == port_id:
                    return item
        return None
