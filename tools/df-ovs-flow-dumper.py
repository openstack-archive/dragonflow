#!/usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import re
import sys
import os_client_config
from oslo_config import cfg
from neutron.agent.common import utils
from neutron.common import config as common_config
from neutronclient.neutron import client
from dragonflow.common import common_params

cfg.CONF.register_opts(common_params.df_opts, 'df')

EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK = 26


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()

class SortedDisplayDict(dict):
   def __str__(self):
       return "{" + ", ".join("%r: %r" % (key, self[key]) for key in sorted(self)) + "}"

class Info():
    def setUp(self):
        creds = credentials()
        tenant_name = creds['project_name']
        auth_url = creds['auth_url'] + "/v2.0"
        self.neutron = client.Client('2.0', username=creds['username'],
             password=creds['password'], auth_url=auth_url,
             tenant_name=tenant_name)

    def _get_ovs_flows(self):
        full_args = ["ovs-ofctl", "dump-flows", 'br-int', '-O Openflow13']
        flows = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return flows

    def _parse_ovs_flows(self, flows):
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            if len(flow) == 0:
                continue
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1]
            res['match'] = fs[-2]
            res['packets'] = fs[4].split('=')[1]
            res['actions'] = fs[-1].split('=')[1]
            res['cookie'] = fs[1].split('=')[1]
            m = re.search('priority=(\d+)', res['match'])
            if m:
                res['priority'] = m.group(1)
                res['match'] = re.sub(r'priority=(\d+),?', '', res['match'])
            flows_as_dicts.append(res)
        return flows_as_dicts

    def ListFlows(self):
        flows = self._get_ovs_flows()
        flows_list = self._parse_ovs_flows(flows)
        flows_list2 = self._ovs_bitify_tables(flows_list)
        return flows_list2

    def _get_ovs_local_ports(self):
        #full_args = ["ovs-dpctl", "show"]
        full_args = ["ovs-ofctl", "show", 'br-int', '-O Openflow13']
        ports = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return ports

    def _parse_ovs_local_ports(self, ports):
        port_list = ports.split("\n")[1:]
        result = list()
        for line in port_list:
            if "addr:" in line:
                line = line.strip()
                m = re.search('\A(\w+)\(([-\w]+)\): addr:(.*?)\Z', line)
                if m:
                    result.append({'id': m.group(1), 'name': m.group(2), 'addr': m.group(3)})
        return result

    def _ovs_bitify_tables(self, flows):
        tables = {'0': 'START', '9': 'APPCHECK', '10': 'ARPINJECT', '11': 'DHCPINJECT', '17': 'L2LOOKUP', '20': 'L3ROUTE', '64': 'OUTPUT' }
        result = list()
        for flow in flows:
            if flow['table'].strip(',') in tables:
                flow['table'] = tables[flow['table'].strip(',')]
            m = re.search('goto_table:(\d+)', flow['actions'])
            if m and m.group(1) in tables:
                flow['actions'] = re.sub('goto_table:(\d+)','goto:'+tables[m.group(1)], flow['actions'])
            m = re.search(r'resubmit\(,(\d+)\)', flow['actions'])
            if m and m.group(1) in tables:
                flow['actions'] = re.sub(r'resubmit\(,(\d+)\)', r'resubmit(,'+tables[m.group(1)]+')', flow['actions'])
            flow['actions'] = re.sub(r'set_field:0x(\d+)[-]>metadata', r'NETWORK=0x\1', flow['actions'])
            flow['match'] = re.sub(r'metadata=0x(\d+)', r'NETWORK=0x\1', flow['match'])
            flow['actions'] = re.sub(r'set_field:0x(\d+)->reg6', r'STAG=0x\1', flow['actions'])
            flow['match'] = re.sub(r'reg6=0x(\d+)', r'STAG=0x\1', flow['match'])
            flow['actions'] = re.sub(r'set_field:0x(\d+)->reg7', r'STAG=0x\1', flow['actions'])
            flow['match'] = re.sub(r'reg7=0x(\d+)', r'DTAG=0x\1', flow['match'])
            flow['match'] = re.sub('tun_id=', 'VTAG=', flow['match'])
            result.append(flow)
        return result


    def ListPorts(self):
        ports = self._get_ovs_local_ports()
        ports = self._parse_ovs_local_ports(ports)
        return ports

    def PrintOvsFlowRow(self, row):
        if 'cookie' in row and row['cookie'] == '0x0,':
            row.pop('cookie')
        if row['packets'] == '0,':
            row.pop('packets')
        priority = row['priority']
        actions = row['actions']
        table = row['table']
        match = row['match']
        row.pop('priority')
        row.pop('actions')
        row.pop('table')
        row.pop('match')
        if len(row) == 0:
            row = ""
        print("%-10s | %-3s | %-50s | %-40s | %s" % (table, priority, match, actions, row))

    def PrintData(self):
        ports = self.neutron.list_ports(retrieve_all=True)
        ports = ports['ports']
        ports2 = dict()
        for port in ports:
            id = port['id'][0:11]
            ports2[id] = port
        networks = self.neutron.list_networks()
        subnets = dict()
        networks = networks['networks']
        for network in networks:
            subnets2 = network['subnets']
            for subnet in subnets2:
                subnets[subnet] = {'name': network['name'], 'router:external': network['router:external']}
        ports = self.ListPorts()
        for port in ports:
            id = port['name'][3:]
            if id in ports2:
                info = ports2[id]
                netinfo = list()
                for subnet in info['fixed_ips']:
                    if 'subnet_id' in subnet and subnet['subnet_id'] in subnets:
                            z = subnet.copy()
                            z.update(subnets[subnet['subnet_id']])
                            netinfo.append(z)
                    else:
                        netinfo.append(subnet) # just copy fixed_ip array
                print(port['id'], port['name'], port['addr'], info['name'], info['device_owner'], netinfo)
            else:
                print(port['id'], port['name'], port['addr'], '-----------------')
        flows = self.ListFlows()
        print("=" * 130)
        print("TABLE:     | PRI | PATTERN                                            | ACTION                                   | More")
        print("=" * 130)
        for flow in flows:
            #print(SortedDisplayDict(flow))
            self.PrintOvsFlowRow(flow)

def main():
    c = Info()
    c.setUp()
    c.PrintData()

if __name__ == '__main__':
    sys.exit(main())
