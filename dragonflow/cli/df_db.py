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
import sys

from dragonflow.cli import utils as cli_utils
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.db import model_framework
from dragonflow.db import models
from dragonflow.db.models import all  # noqa

db_tables = list(model_framework.iter_tables()) + [db_common.UNIQUE_KEY_TABLE]
nb_api = None


def _x_get_model(table):
    try:
        return model_framework.get_model(table)
    except KeyError:
        print('Table not found: ' + table)
        sys.exit(1)


def print_tables():
    columns = ['table']
    tables = [{'table': table} for table in db_tables]
    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(columns, tables)
    labels[0] = 'DB Tables'
    cli_utils.print_list(tables, columns, formatters=formatters,
                         field_labels=labels)


def print_table(table):
    model = _x_get_model(table)
    values = nb_api.get_all(model)

    if not values:
        print('Table is empty: ' + table)
        return

    keys = [{'key': value.id} for value in values]

    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(['key'], keys)
    labels[0] = 'Keys for table'
    cli_utils.print_list(keys, ['key'], formatters=formatters,
                         field_labels=labels)


def print_whole_table(table):
    if table == db_common.UNIQUE_KEY_TABLE:
        keys = nb_api.driver.get_all_keys(table)
        values = [{'id': key, table: int(nb_api.driver.get_key(table, key))}
                  for key in keys]
        columns = ['id', table]
        labels, formatters = \
            cli_utils.get_list_table_columns_and_formatters(columns, values)
        cli_utils.print_list(values, columns, formatters=formatters,
                             field_labels=columns)
        return

    model = _x_get_model(table)
    value_models = nb_api.get_all(model)
    values = [value.to_struct() for value in value_models]

    if not values:
        print('Table is empty: ' + table)
        return

    columns = values[0].keys()
    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(columns, values)
    cli_utils.print_list(values, columns, formatters=formatters,
                         field_labels=labels)


def print_key(table, key):
    model = _x_get_model(table)
    try:
        value = nb_api.get(model(id=key))
    except df_exceptions.DBKeyNotFound:
        print('Key not found: ' + table)
        return

    # It will be too difficult to print all type of data in table
    # therefore using print dict for dictionary type otherwise
    # using old approach for print.
    if isinstance(value, model_framework.ModelBase):
        cli_utils.print_dict(value.to_struct())
    else:
        print(value)


def bind_port_to_localhost(port_id):
    lport = nb_api.get(models.LogicalPort(id=port_id))
    chassis_name = socket.gethostname()
    lport.chassis = chassis_name
    nb_api.update(lport)


def clean_whole_table(table):
    model = _x_get_model(table)
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
    model = _x_get_model(table)
    try:
        nb_api.delete(model(id=key))
    except df_exceptions.DBKeyNotFound:
        print('Key %s is not found in table %s.' % (key, table))


def _check_valid_table(parser, table_name):
    if table_name not in db_tables:
        parser.exit(
            status=2,
            message="<table> must be one of the following:\n %s\n" % db_tables)


def add_table_command(subparsers):
    def handle(args):
        print_tables()

    sub_parser = subparsers.add_parser('tables', help="Print all the db "
                                                      "tables.")
    sub_parser.set_defaults(handle=handle)


def add_ls_command(subparsers):
    def handle(args):
        table = args.table
        _check_valid_table(sub_parser, table)
        print_table(table)

    sub_parser = subparsers.add_parser('ls', help="Print all the keys for "
                                                  "specific table.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.set_defaults(handle=handle)


def add_get_command(subparsers):
    def handle(args):
        table = args.table
        key = args.key
        _check_valid_table(sub_parser, table)
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
        _check_valid_table(sub_parser, table)
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
