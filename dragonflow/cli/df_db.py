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

from neutron.common import config as common_config
from oslo_serialization import jsonutils

from dragonflow.cli import utils as cli_utils
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import models

db_tables = list(models.table_class_mapping) + ['unique_key', 'portstats']


def print_tables():
    columns = ['table']
    tables = [{'table': table} for table in db_tables]
    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(columns, tables)
    labels[0] = 'DB Tables'
    cli_utils.print_list(tables, columns, formatters=formatters,
                         field_labels=labels)


def print_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        keys = []

    if not keys:
        print('Table is empty: ' + table)
        return

    for count, key in enumerate(keys):
        keys[count] = {'key': key}

    labels, formatters = \
        cli_utils.get_list_table_columns_and_formatters(['key'], keys)
    labels[0] = 'Keys for table'
    cli_utils.print_list(keys, ['key'], formatters=formatters,
                         field_labels=labels)


def print_whole_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)
        return

    if not keys:
        print('Table is empty: ' + table)
        return

    raw_values = [db_driver.get_key(table, key) for key in keys]
    values = [jsonutils.loads(value) for value in raw_values if value]
    if isinstance(values[0], dict):
        columns = values[0].keys()
        labels, formatters = \
            cli_utils.get_list_table_columns_and_formatters(columns, values)
        cli_utils.print_list(values, columns, formatters=formatters,
                             field_labels=labels)
    elif isinstance(values[0], int):
        for l, value in enumerate(values):
            values[l] = {table: value}

        columns = [table]
        labels, formatters = \
            cli_utils.get_list_table_columns_and_formatters(columns, values)
        cli_utils.print_list(values, columns, formatters=formatters,
                             field_labels=columns)


def print_key(db_driver, table, key):
    try:
        value = db_driver.get_key(table, key)
    except df_exceptions.DBKeyNotFound:
        print('Key not found: ' + table)
        return

    value = jsonutils.loads(value)
    # It will be too difficult to print all type of data in table
    # therefore using print dict for dictionary type otherwise
    # using old approach for print.
    if isinstance(value, dict):
        cli_utils.print_dict(value)
    else:
        print(value)


def bind_port_to_localhost(db_driver, port_id):
    lport_str = db_driver.get_key(models.LogicalPort.table_name, port_id)
    lport = jsonutils.loads(lport_str)
    chassis_name = socket.gethostname()
    lport['chassis'] = chassis_name
    lport_json = jsonutils.dumps(lport)
    db_driver.set_key(models.LogicalPort.table_name, port_id, lport_json)


def clean_whole_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)
        return

    for key in keys:
        try:
            db_driver.delete_key(table, key)
        except df_exceptions.DBKeyNotFound:
            print('Key not found: ' + key)


def drop_table(db_driver, table):
    try:
        db_driver.delete_table(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)


def create_table(db_driver, table):
    db_driver.create_table(table)
    print('Table %s is created.' % table)


def remove_record(db_driver, table, key):
    try:
        db_driver.delete_key(table, key)
    except df_exceptions.DBKeyNotFound:
        print('Key %s is not found in table %s.' % (key, table))


def _check_valid_table(parser, table_name):
    if table_name not in db_tables:
        parser.exit(
            status=2,
            message="<table> must be one of the following:\n %s\n" % db_tables)


def add_table_command(subparsers):
    def handle(db_driver, args):
        print_tables()

    sub_parser = subparsers.add_parser('tables', help="Print all the db "
                                                      "tables.")
    sub_parser.set_defaults(handle=handle)


def add_ls_command(subparsers):
    def handle(db_driver, args):
        table = args.table
        _check_valid_table(sub_parser, table)
        print_table(db_driver, table)

    sub_parser = subparsers.add_parser('ls', help="Print all the keys for "
                                                  "specific table.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.set_defaults(handle=handle)


def add_get_command(subparsers):
    def handle(db_driver, args):
        table = args.table
        key = args.key
        _check_valid_table(sub_parser, table)
        print_key(db_driver, table, key)

    sub_parser = subparsers.add_parser('get', help="Print value for specific "
                                                   "key.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.add_argument('key', help='The key of the resource.')
    sub_parser.set_defaults(handle=handle)


def add_dump_command(subparsers):
    def handle(db_driver, args):
        for table in db_tables:
            print_whole_table(db_driver, table)

    sub_parser = subparsers.add_parser('dump', help="Dump content of all "
                                                    "tables.")
    sub_parser.set_defaults(handle=handle)


def add_bind_command(subparsers):
    def handle(db_driver, args):
        port_id = args.port_id
        bind_port_to_localhost(db_driver, port_id)

    sub_parser = subparsers.add_parser('bind', help="Bind a port to "
                                                    "localhost.")
    sub_parser.add_argument('port_id', help='The ID of the port.')
    sub_parser.set_defaults(handle=handle)


def add_clean_command(subparsers):
    def handle(db_driver, args):
        for table in db_tables:
            clean_whole_table(db_driver, table)

    sub_parser = subparsers.add_parser('clean', help="Clean up all keys.")
    sub_parser.set_defaults(handle=handle)


def add_rm_command(subparsers):
    def handle(db_driver, args):
        table = args.table
        key = args.key
        _check_valid_table(sub_parser, table)
        remove_record(db_driver, table, key)

    sub_parser = subparsers.add_parser('rm', help="Remove the specified DB "
                                                  "record.")
    sub_parser.add_argument('table', help='The name of the table.')
    sub_parser.add_argument('key', help='The key of the resource.')
    sub_parser.set_defaults(handle=handle)


def add_init_command(subparsers):
    def handle(db_driver, args):
        for table in db_tables:
            create_table(db_driver, table)

    sub_parser = subparsers.add_parser('init', help="Initialize all tables.")
    sub_parser.set_defaults(handle=handle)


def add_dropall_command(subparsers):
    def handle(db_driver, args):
        for table in db_tables:
            drop_table(db_driver, table)

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

    common_config.init(['--config-file',
                        '/etc/neutron/dragonflow.ini',
                        '--config-file',
                        '/etc/neutron/neutron.conf'])
    db_driver = df_utils.load_driver(
        cfg.CONF.df.nb_db_class,
        df_utils.DF_NB_DB_DRIVER_NAMESPACE)
    db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                         db_port=cfg.CONF.df.remote_db_port,
                         config=cfg.CONF.df)

    args.handle(db_driver, args)


if __name__ == "__main__":
    main()
