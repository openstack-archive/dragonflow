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

import rethinkdb
import json

from dragonflow.db import db_api
import threading
import sys

STDERR = sys.stderr


def excepthook(*args):
    print >> STDERR, 'caught'
    print >> STDERR, args


sys.excepthook = excepthook


class RethinkDbDriver(db_api.DbApi):
    db_ip = None
    db_port = None

    def __init__(self):
        super(RethinkDbDriver, self).__init__()
        self.client = rethinkdb
        self.current_key = 0
        self.db_name = 'dragonflow'

    def initialize(self, db_ip, db_port, **args):
        self.db_ip = db_ip
        self.db_port = db_port
        self.client.connect(host=db_ip, port=db_port).repl()

    def support_publish_subscribe(self):
        return True

    def get_key(self, table, key):
        return json.dumps(self.client.db('dragonflow').table(table).get(key).run())

    def set_key(self, table, key, value):
        self.client.db('dragonflow').table(table).get(key).update(json.loads(value), return_changes=True).run()

    def create_key(self, table, key, value):
        self.client.db('dragonflow').table(table).insert(json.loads(value), return_changes=True).run()

    def delete_key(self, table, key):
        self.client.db('dragonflow').table(table).get(key).delete().run()

    def get_all_entries(self, table):
        res = []
        cursor = self.client.db('dragonflow').table(table).run()
        for entry in cursor:
            res.append(json.dumps(entry))
        return res

    def single_feed(self, table, callback):
        import time
        print "Feed Table name: " + table + " on host: " + self.db_ip + " on port: " + self.db_port
        conn = self.client.connect(host=self.db_ip, port=self.db_port)
        cursor = self.client.db('dragonflow').table(table).changes().run(conn)
        for entry in cursor:
            print "######################## FULL ENTRY ################################"
            print entry
            if entry['old_val'] is None:
                act = {'action': 'create'}
                key = entry['new_val']['name']
            elif entry['new_val'] is None:
                act = {'action': 'delete'}
                key = entry['old_val']['name']
            else:
                act = {'action': 'set'}
                key = entry['new_val']['name']
            entry.update(act)
            attempts = 0
            while True:
                try:
                    callback(table, key, entry['action'], entry['new_val'])
                    break
                except Exception as e:
                    if attempts < 1000:
                        pass
                    else:
                        raise e
                attempts+=1
                time.sleep(1)

    def wait_for_db_changes(self, prefix, callback):
        all_tables = self.client.db('dragonflow').table_list().run()
        for table in all_tables:
            if table.encode('ascii', 'ignore').startswith(prefix):
                print "Starting thread for table: " + table
                try:
                    t = threading.Thread(target=self.single_feed, args=(table, callback))
                    t.start()
                except Exception as e:
                    raise e

    @property
    def _allocate_unique_key(self):
        table = 'tunnel_key'
        db_id = 1
        prev_value = 0
        try:
            return_val = self.client.db('dragonflow').table(table).get(db_id).update({'key': self.client.row['key'].add(1)}, return_changes=True).run()
            new_value = return_val['changes'][0]['new_val']['key']
            prev_value = return_val['changes'][0]['old_val']['key']
            return new_value
        except Exception as e:
            if prev_value == 0:
                self.client.db('dragonflow').table(table).insert({'name': db_id, 'key': 1}, return_changes=False).run()
                return 1
            raise e

    def allocate_unique_key(self):
        while True:
            try:
                return self._allocate_unique_key
            except Exception:
                pass


# Tests
def callback_foo(table, key, action, value):
    print "######################## RUN CALLBACK TEST #################################"
    print "######################## TABLE:            #################################"
    print table
    print "######################## KEY:              #################################"
    print key
    print "######################## ACTION:           #################################"
    print action
    print "######################## NEW VALUE:        #################################"
    print value
    print

if __name__ == "__main__":
    RD = RethinkDbDriver()
    RD.initialize("127.0.0.1", "28015")
    # Mock Data

    test_data = '{"external_ids": {"neutron:router_name": "router1"}, "name": "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af",' \
                '"ports": [{"network": "10.0.0.1/24", "lswitch": "neutron-8c46938d-4201-4223-abb1-8b4830ea6dcc", "mac": "fa:16:3e:e2:16:63",' \
                '"tunnel_key": 2, "lrouter": "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af", "name": "3fd0768f-2acd-4e5d-bba9-21be7e470571"},' \
                '{"network": "fd63:2be9:34d8::1/64", "lswitch": "neutron-8c46938d-4201-4223-abb1-8b4830ea6dcc", "mac": "fa:16:3e:f1:d1:f1",' \
                '"tunnel_key": 4, "lrouter": "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af", "name": "55f20f8d-e13b-436a-87cf-0bddf612561f"}]}'
    test_data_1 = '{"external_ids": {"neutron:router_name": "router3"}}'
    test_data_2 = '{"external_ids": {"neutron:router_name": "router4"}, "name": "neutron-9k8b2cc3-698d-4fc3-aba3-379c8770d8af",' \
                  '"ports": [{"network": "10.0.0.1/24", "lswitch": "neutron-8c46938d-4201-4223-abb1-8b4830ea6dcc", "mac": "fa:16:3e:e2:16:63",' \
                  '"tunnel_key": 2, "lrouter": "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af", "name": "3fd0768f-2acd-4e5d-bba9-21be7e470571"},' \
                  '{"network": "fd63:2be9:34d8::1/64", "lswitch": "neutron-8c46938d-4201-4223-abb1-8b4830ea6dcc", "mac": "fa:16:3e:f1:d1:f1",' \
                  '"tunnel_key": 4, "lrouter": "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af", "name": "55f20f8d-e13b-436a-87cf-0bddf612561f"}]}'

    # UniTests
    test_nmb = 0
    output = RD.get_all_entries('dragonflow')
    test_nmb+=1

    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Delete and Create Table "
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "GetList - Empty database: "
    print(output)
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Creating 2 entries with UUID neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af and neutron-9k8b2cc3-698d-4fc3-aba3-379c8770d8af"
    RD.create_key('dragonflow', '3fd0768f-2acd-4e5d-bba9-21be7e470571', test_data)
    RD.create_key('dragonflow', '3fd0768f-2acd-4e5d-bba9-21be7e470571', test_data_2)
    output = RD.get_all_entries('dragonflow')
    print "GetList: "
    for entry in output:
        print "################### ENTRY: ###################"
        print(entry)
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    output = RD.get_key('dragonflow', "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af")
    print "Get by Key neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af: "
    print (output)
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Delete Value by Key neutron-9k8b2cc3-698d-4fc3-aba3-379c8770d8af and print list"
    RD.delete_key('dragonflow', "neutron-9k8b2cc3-698d-4fc3-aba3-379c8770d8af")
    output = RD.get_all_entries('dragonflow')
    print (output)
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Run feeds on all tables"
    RD.wait_for_db_changes('dragon', callback_foo)
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Allocate unique key"
    output = RD.allocate_unique_key()
    print "New allocated falue is: ", output
    print
    print
    test_nmb+=1
    print "######################## TEST NUMBER:" + str(test_nmb) + " ###################################"
    print "Update Entry by Key neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af (router1-> router3): "
    RD.set_key('dragonflow', "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af", test_data_1)
    output = RD.get_key('dragonflow', "neutron-8b8a2dd9-698d-4fc3-aba3-379c8770d8af")
    print "Updated Value"
    print (output)
    print
    print
    print "###########STATIC TESTS DONE: " + str(test_nmb) + " of 6, STARTS S/N TESTS ####################"
