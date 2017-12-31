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

import argparse
import socket

from dragonflow.cli import utils as cli_utils
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.db import model_framework
from dragonflow.db.models import all  # noqa
from dragonflow.db.models import l2

db_tables = list(model_framework.iter_tables()) + [db_common.UNIQUE_KEY_TABLE]
nb_api = None


def _get_model_or_exit(table):
    """
    Return the model by table name. If no such model is found, raise
    SystemExit, which (in general should) exit the process.
    """
    try:
        return model_framework.get_model(table)
    except KeyError:
        print('Table not found: ' + table)
        raise SystemExit(1)


def _print_list(columns, values, first_label=None):
    """
    Print the given columns from the given values. You can override the label
    of the first column with 'first_label'.
    :param columns:     The columns to print from values
    :type columns:      List of strings
    :param values:      The values to print
    :type values:       List of dict
    :param first_label: The label of the first column
    :type first_label:  String
    """
    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(columns, values)
    if first_label:
        labels[0] = first_label
    cli_utils.print_list(values, columns, formatters=formatters,
                         field_labels=labels)


def print_tables():
    columns = ['table']
    tables = [{'table': table} for table in db_tables]
    _print_list(columns, tables, 'DB Tables')


def print_table(table):
    if table == db_common.UNIQUE_KEY_TABLE:
        keys = nb_api.driver.get_all_keys(table)
        values = [{'id': key} for key in keys]
        _print_list(['id'], values)
        return
    model = _get_model_or_exit(table)
    instances = nb_api.get_all(model)

    if not instances:
        print('Table is empty: ' + table)
        return

    keys = [{'key': instance.id} for instance in instances]
    _print_list(['key'], keys, 'Keys for table')


def print_whole_table(table):
    if table == db_common.UNIQUE_KEY_TABLE:
        keys = nb_api.driver.get_all_keys(table)
        values = [{'id': key, table: int(nb_api.driver.get_key(table, key))}
                  for key in keys]
        columns = ['id', table]
        _print_list(columns, values)
        return

    model = _get_model_or_exit(table)
    instances = nb_api.get_all(model)
    values = [instance.to_struct() for instance in instances]

    if not values:
        print('Table is empty: ' + table)
        return

    columns = values[0].keys()
    _print_list(columns, values)


def print_key(table, key):
    if table == db_common.UNIQUE_KEY_TABLE:
        value = nb_api.driver.get_key(table, key)
        value_dict = {'id': key, table: int(value)}
        cli_utils.print_dict(value_dict)
        return
    model = _get_model_or_exit(table)
    try:
        value = nb_api.get(model(id=key))
    except df_exceptions.DBKeyNotFound:
        print('Key not found: ' + table)
        return
    cli_utils.print_dict(value.to_struct())


def bind_port_to_localhost(port_id):
    lport = nb_api.get(l2.LogicalPort(id=port_id))
    chassis_name = socket.gethostname()
    lport.binding = l2.PortBinding(type=l2.BINDING_CHASSIS,
                                   chassis=chassis_name)
    nb_api.update(lport)


def clean_whole_table(table):
    if table == db_common.UNIQUE_KEY_TABLE:
        keys = nb_api.driver.get_all_keys(table)
        for key in keys:
            try:
                nb_api.driver.delete_key(table, key)
            except df_exceptions.DBKeyNotFound:
                print('Unique key not found: ' + key)
        return
    model = _get_model_or_exit(table)
    values = nb_api.get_all(model)

    for value in values:
        try:
            nb_api.delete(value)
        except df_exceptions.DBKeyNotFound:
            print('Instance not found: ' + value)


def drop_table(table):
    try:
        nb_api.driver.delete_table(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)


def create_table(table):
    nb_api.driver.create_table(table)
    print('Table %s is created.' % table)


def remove_record(table, key):
    if table == db_common.UNIQUE_KEY_TABLE:
        try:
            nb_api.driver.delete_key(table, key)
        except df_exceptions.DBKeyNotFound:
            print('Key %s is not found in table %s.' % (key, table))
        return
    model = _get_model_or_exit(table)
    try:
        nb_api.delete(model(id=key))
    except df_exceptions.DBKeyNotFound:
        print('Key %s is not found in table %s.' % (key, table))


def add_table_command(subparsers):
    def handle(args):
        print_tables()

    sub_parser = subparsers.add_parser('tables', help="Print all the db "
                                                      "tables.")
    sub_parser.set_defaults(handle=handle)


def add_ls_command(subparsers):
    def handle(args):
        table = args.table
        print_table(table)

    sub_parser = subparsers.add_parser('ls', help="Print all the keys for "
                                                  "specific table.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.set_defaults(handle=handle)


def add_get_command(subparsers):
    def handle(args):
        table = args.table
        key = args.key
        print_key(table, key)

    sub_parser = subparsers.add_parser('get', help="Print value for specific "
                                                   "key.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.add_argument('key', help='The key of the resource.')
    sub_parser.set_defaults(handle=handle)


def add_dump_command(subparsers):
    def handle(args):
        for table in db_tables:
            print_whole_table(table)

    sub_parser = subparsers.add_parser('dump', help="Dump content of all "
                                                    "tables.")
    sub_parser.set_defaults(handle=handle)


def add_bind_command(subparsers):
    def handle(args):
        port_id = args.port_id
        bind_port_to_localhost(port_id)

    sub_parser = subparsers.add_parser('bind', help="Bind a port to "
                                                    "localhost.")
    sub_parser.add_argument('port_id', help='The ID of the port.')
    sub_parser.set_defaults(handle=handle)


def add_clean_command(subparsers):
    def handle(args):
        for table in db_tables:
            clean_whole_table(table)

    sub_parser = subparsers.add_parser('clean', help="Clean up all keys.")
    sub_parser.set_defaults(handle=handle)


def add_rm_command(subparsers):
    def handle(args):
        table = args.table
        key = args.key
        remove_record(table, key)

    sub_parser = subparsers.add_parser('rm', help="Remove the specified DB "
                                                  "record.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.add_argument('key', help='The key of the resource.')
    sub_parser.set_defaults(handle=handle)


def add_init_command(subparsers):
    def handle(args):
        for table in db_tables:
            create_table(table)

    sub_parser = subparsers.add_parser('init', help="Initialize all tables.")
    sub_parser.set_defaults(handle=handle)


def add_dropall_command(subparsers):
    def handle(args):
        for table in db_tables:
            drop_table(table)

    sub_parser = subparsers.add_parser('dropall', help="Drop all tables.")
    sub_parser.set_defaults(handle=handle)


def main():
    parser = argparse.ArgumentParser(usage="missing command name "
                                           "(use --help for help)")
    subparsers = parser.add_subparsers(title='subcommands',
                                       description='valid subcommands')
    add_table_command(subparsers)
    add_ls_command(subparsers)
    add_dump_command(subparsers)
    add_get_command(subparsers)
    add_bind_command(subparsers)
    add_clean_command(subparsers)
    add_rm_command(subparsers)
    add_init_command(subparsers)
    add_dropall_command(subparsers)
    args = parser.parse_args()

    df_utils.config_parse()

    global nb_api
    nb_api = api_nb.NbApi.get_instance(False)

    args.handle(args)


if __name__ == "__main__":
    main()
