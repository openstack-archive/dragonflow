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

import re

from neutron.agent.common import utils as agent_utils
from neutron.common import utils as n_utils

from dragonflow.common import exceptions
from dragonflow.controller.common import constants as df_const
from dragonflow.tests.common import constants as const


WAIT_UNTIL_TRUE_DEFAULT_TIMEOUT = 60
WAIT_UNTIL_TRUE_DEFAULT_SLEEP = 1


class TestTimeoutException(exceptions.DragonflowException):
    message = 'Operation in testing timed out'


def wait_until_true(predicate, timeout=WAIT_UNTIL_TRUE_DEFAULT_TIMEOUT,
                    sleep=WAIT_UNTIL_TRUE_DEFAULT_SLEEP, exception=None):
    """Wait until predicate() returns true, and return. Raises a
    TestTimeoutException after timeout seconds, polling once every sleep
    seoncds.
    """
    exception = exception or TestTimeoutException
    return n_utils.wait_until_true(predicate, timeout, sleep, exception)


def wait_until_is_and_return(predicate, timeout=const.DEFAULT_CMD_TIMEOUT,
                             sleep=1, exception=None):
    container = {}

    def internal_predicate():
        container['value'] = predicate()
        return container['value']

    wait_until_true(internal_predicate, timeout, sleep, exception)
    return container.get('value')


def wait_until_none(predicate, timeout=const.DEFAULT_CMD_TIMEOUT,
                    sleep=1, exception=None):
    def internal_predicate():
        ret = predicate()
        if ret:
            return False
        return True
    wait_until_true(internal_predicate, timeout, sleep, exception)


def check_dhcp_ip_rule(flows, dhcp_ip):
    goto_dhcp = 'goto_table:' + str(df_const.DHCP_TABLE)
    dhcp_ports = ',tp_src=' + str(df_const.DHCP_CLIENT_PORT) + \
                 ',tp_dst=' + str(df_const.DHCP_SERVER_PORT)
    for flow in flows:
        if (flow['table'] == str(df_const.SERVICES_CLASSIFICATION_TABLE)
            and flow['actions'] == goto_dhcp):
            if ('nw_dst=' + dhcp_ip + dhcp_ports in flow['match']):
                return True
    return False


def print_command(full_args, run_as_root=False):
    print ('{}'.format(agent_utils.execute(
        full_args,
        run_as_root=run_as_root,
        process_input=None,
    )))


class OvsFlowsParser(object):

    def get_ovs_flows(self, integration_bridge):
        full_args = ["ovs-ofctl", "dump-flows", integration_bridge,
                     "-O Openflow13"]
        flows = agent_utils.execute(full_args, run_as_root=True,
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
