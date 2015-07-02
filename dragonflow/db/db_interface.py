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


class DbConnection(object):

    def initialize(self):
        pass

    def start(self):
        pass

    def sync(self):
        pass

    def get_table(self, name):
        pass

    def create_transaction(self, name):
        pass


class DbTransaction(object):

    def commit(self):
        pass


class DbTable(object):

    def create_entry(self, key=None, entry=None, txn=None):
        pass

    def get_entry(self, key):
        pass

    def get_entries(self):
        pass


class DbEntry(object):

    def set_value(self, column, value, txn=None):
        pass

    def get_value(self, column, txn=None):
        pass

    def verify(self, column):
        pass
