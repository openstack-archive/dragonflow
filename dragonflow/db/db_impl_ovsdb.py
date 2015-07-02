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

from dragonflow.db import db_interface

from ovs.db import idl

from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils


class DbOVSDBConnection(db_interface.DbConnection):

    def __init__(self, db_name, ip, protocol='tcp', port='6640', timeout=10):
        super(DbOVSDBConnection, self).__init__()
        self.ip = ip
        self.db_name = db_name
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self.ovsdb = None
        self.idl = None

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = connection.Connection(db_connection,
                                           self.timeout,
                                           self.db_name)

    def start(self):
        self.ovsdb.start()
        self.idl = self.ovsdb.idl

    def sync(self):
        self.idl.run()

    def get_table(self, name):
        table_instance = self.idl.tables[name]
        table = DbOVSDBTable(name, table_instance)
        return table

    def create_transaction(self, name):
        return DbOVSDBTransaction(name, self.idl)


class DbOVSDBTransaction(db_interface.DbTransaction):

    def __init__(self, name, idl_obj):
        self.name = name
        self.transaction = idl.Transaction(idl_obj)

    def commit(self):
        status = self.transaction.commit_block()
        return status


class DbOVSDBTable(db_interface.DbTable):

    def __init__(self, name, table_inst):
        super(DbOVSDBTable, self).__init__()
        self.table_name = name
        self.table = table_inst

    def create_entry(self, key=None, txn=None):
        transaction = txn.transaction
        row = transaction.insert(self.idl_sb.tables[self.table_name])
        return DbOVSDBEntry(row)

    def get_entry(self, key):
        pass

    def get_entries(self):
        pass


class DbOVSDBEntry(db_interface.DbEntry):

    def __init__(self, row):
        self.row = row

    def set_value(self, column, value, txn=None):
        # Value could also be another DBEntry object
        setattr(self.row, column, value)

    def get_value(self, column, default_value, txn=None):
        # TODO(gal) can return value or another DBEntry object (reference)
        return getattr(self.row, column, default_value)

    def verify(self, column):
        self.row.verify(column)