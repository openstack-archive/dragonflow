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

import functools
import re

import mock
import netaddr
from neutron.agent.common import utils as agent_utils
from neutron.common import utils as n_utils
from neutron_lib import constants as n_const
import six

from dragonflow.common import exceptions
from dragonflow.controller.common import constants as df_const
from dragonflow.db import db_store
from dragonflow.db import model_proxy
from dragonflow.db.models import l2
from dragonflow.ovsdb import vswitch_impl
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


def find_logical_port(nb_api, ip=None, mac=None):
    ports = nb_api.get_all(l2.LogicalPort)
    for port in ports:
        if ip:
            if not isinstance(ip, netaddr.IPAddress):
                ip = netaddr.IPAddress(ip)
            if port.ip != ip:
                continue
        if mac:
            if not isinstance(mac, netaddr.EUI):
                mac = netaddr.EUI(mac)
            if port.mac != mac:
                continue
        return port
    return None


def ip_version_to_ethertype(ip_version):
    if ip_version == n_const.IP_VERSION_4:
        return n_const.IPv4
    if ip_version == n_const.IP_VERSION_6:
        return n_const.IPv6
    raise exceptions.InvalidEtherTypeException(ethertype=ip_version)


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


class OvsTestApi(vswitch_impl.OvsApi):

    def get_port_id_by_vm_id(self, vm_id):
        columns = {'external_ids', 'name'}
        interfaces = self.ovsdb.db_find(
            'Interface', ('external_ids', '=', {'vm-id': vm_id}),
            columns=columns).execute()

        for interface in interfaces:
            if (self.integration_bridge !=
                    self._get_bridge_for_iface(interface['name'])):
                # interfaces with the vm-id in its external_ids column might
                # exists in different bridges
                continue
            return interface['external_ids'].get('iface-id')

    def get_ovs_port_by_id_with_specified_columns(
            self, port_id, specified_columns):
        port_name = self._get_port_name_by_id(port_id)
        if not port_name:
            return

        columns = {'name'}
        columns.update(specified_columns)
        ports = self.ovsdb.db_find(
            'Port', ('name', '=', port_name), columns=columns).execute()
        if ports:
            return ports[0]

    def get_qos_info_by_port_id(self, port_id):
        columns = {'external_ids', 'queues', '_uuid'}
        port_qoses = self.ovsdb.db_find(
            'QoS', ('external_ids', '=', {'iface-id': port_id}),
            columns=columns).execute()
        if port_qoses:
            return port_qoses[0]

    def get_queue_info_by_port_id(self, port_id):
        columns = {'external_ids', 'other_config', 'dscp', '_uuid'}
        queues = self.ovsdb.db_find(
            'Queue', ('external_ids', '=', {'iface-id': port_id}),
            columns=columns).execute()
        if queues:
            return queues[0]


class empty_wrapper(object):
    def __init__(self, type):
        pass

    def __call__(self, f):
        @six.wraps(f)
        def wrapped_f(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapped_f


def add_objs_to_db_store(*objs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            db_store_inst = db_store.get_instance()
            for obj in objs:
                db_store_inst.update(obj)
            try:
                return func(*args, **kwargs)
            finally:
                for obj in objs:
                    db_store_inst.delete(obj)
        return wrapper
    return decorator


def with_local_objects(*objs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            db_store_inst = db_store.get_instance()
            for obj in objs:
                db_store_inst.update(obj)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def with_nb_objects(*objs):
    def _get_all(model, topic=None):
        res = [o for o in objs if type(o) == model]
        if topic is not None:
            res = [o for o in res if o.topic == topic]
        return res

    def _get(obj):
        if model_proxy.is_model_proxy(obj):
            model = obj.get_proxied_model()
        else:
            model = type(obj)
        objs = _get_all(model)
        for o in objs:
            if obj.id == o.id:
                return o

    def decorator(func):
        @functools.wraps(func)
        def wrapper(obj, *args, **kwargs):
            with mock.patch.object(
                obj.nb_api, 'get_all', side_effect=_get_all
            ), mock.patch.object(
                obj.nb_api, 'get', side_effect=_get,
            ):
                return func(obj, *args, **kwargs)
        return wrapper
    return decorator
