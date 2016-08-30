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

import socket
import sys

from neutron.common import config as common_config
from oslo_config import cfg
from oslo_serialization import jsonutils

from dragonflow.common import common_params
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils

cfg.CONF.register_opts(common_params.df_opts, 'df')

db_tables = ['lport', 'lswitch', 'lrouter', 'chassis', 'secgroup',
             'tunnel_key', 'floatingip', 'publisher']

usage_str = "The following commands are supported:\n" \
            "1) df-db ls - print all the db tables \n" \
            "2) df-db ls <table_name> - print all the keys for specific table \n" \
            "3) df-db get <table_name> <key> - print value for specific key\n" \
            "4) df-db dump - dump all tables\n" \
            "5) df-db bind <port id> - bind a port to localhost\n" \
            "6) df-db clean - clean up all keys\n" \
            "7) df-db rm <table name> <key> - remove the specified db record\n" \
            "8) df-db init - initialize all tables\n" \
            "9) df-db dropall - drop all tables\n"


def print_tables():
    print(' ')
    print('DB Tables')
    print('----------')
    for table in db_tables:
        print table
    print(' ')


def print_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        keys = []
    print(' ')
    print('Keys for table ' + table)
    print('------------------------------------------------------------')
    for key in keys:
        print key
    print(' ')


def print_whole_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)
        return
    print(' ')
    print('------------------------------------------------------------')
    print('Table = ' + table)
    print('------------------------------------------------------------')
    for key in keys:
        value = db_driver.get_key(table, key)
        if value:
            print('Key = ' + key + ' , Value = ' + value)
    print(' ')


def print_key(db_driver, table, key):
    try:
        value = db_driver.get_key(table, key)
    except df_exceptions.DBKeyNotFound:
        print('Key not found: ' + table)
        return
    print(' ')
    print('Table = ' + table + ' , Key = ' + key)
    print('------------------------------------------------------------')
    print value
    print(' ')


def bind_port_to_localhost(db_driver, port_id):
    lport_str = db_driver.get_key('lport', port_id)
    lport = jsonutils.loads(lport_str)
    chassis_name = socket.gethostname()
    lport['chassis'] = chassis_name
    lport_json = jsonutils.dumps(lport)
    db_driver.set_key('lport', port_id, lport_json)


def clean_whole_table(db_driver, table):
    try:
        keys = db_driver.get_all_keys(table)
    except df_exceptions.DBKeyNotFound:
        print('Table not found: ' + table)
        return
    for key in keys:
        db_driver.delete_key(table, key)


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


def main():
    if len(sys.argv) < 2:
        print usage_str
        return

    common_config.init(['--config-file', '/etc/neutron/neutron.conf'])
    db_driver = df_utils.load_driver(
        cfg.CONF.df.nb_db_class,
        df_utils.DF_NB_DB_DRIVER_NAMESPACE)
    db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                         db_port=cfg.CONF.df.remote_db_port,
                         config=cfg.CONF.df)

    action = sys.argv[1]

    if action == 'ls' and len(sys.argv) < 4:
        if len(sys.argv) == 2:
            print_tables()
            return
        table = sys.argv[2]
        if table not in db_tables:
            print "<table> must be one of the following:"
            print db_tables
            return
        print_table(db_driver, table)
        return

    if action == 'get' and len(sys.argv) < 5:
        if len(sys.argv) < 4:
            print "must supply a key"
            print usage_str
            return
        table = sys.argv[2]
        if table not in db_tables:
            print "<table> must be one of the following:"
            print db_tables
            return
        key = sys.argv[3]
        print_key(db_driver, table, key)
        return

    if action == 'dump' and len(sys.argv) < 3:
        for table in db_tables:
            print_whole_table(db_driver, table)
        return

    if action == 'bind' and len(sys.argv) < 4:
        if len(sys.argv) < 3:
            print "must supply a key"
            print usage_str
            return
        port_id = sys.argv[2]
        bind_port_to_localhost(db_driver, port_id)
        return

    if action == 'clean' and len(sys.argv) < 3:
        for table in db_tables:
            clean_whole_table(db_driver, table)
        return

    if action == 'init' and len(sys.argv) < 3:
        for table in db_tables:
            create_table(db_driver, table)
        return

    if action == 'dropall' and len(sys.argv) < 3:
        for table in db_tables:
            drop_table(db_driver, table)
        return

    if action == 'rm' and len(sys.argv) < 5:
        if len(sys.argv) < 4:
            print "must supply a key"
            print usage_str
            return
        table = sys.argv[2]
        if table not in db_tables:
            print "<table> must be one of the following: %s" % db_tables
            return
        key = sys.argv[3]
        remove_record(db_driver, table, key)
        return

    print usage_str


if __name__ == "__main__":
    main()
