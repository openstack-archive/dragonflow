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

# !/usr/bin/python

import getopt
import rethinkdb as R
import sys
import time


def main(argv):
    db_ip = ''
    db_port = ''
    deleteDB = False
    try:
        opts, args = getopt. \
            getopt(sys.argv[1:],
                   'd:t:i:p:r', ['-t val', '-i val', '-p val', '-r val'])
    except getopt.GetoptError:
        print ('table_setup_rethinkdb.py '
               '-t <table_name>,<table_name>..<table_name>'
               ' -d -i <db_ip> -p <db_port>')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print ('table_setup_rethinkdb.py '
                   '-t <table_name> / -d -i <db_ip> -p <db_port>')
            sys.exit()
        elif opt in "-t":
            db_table = arg.split(',')
        elif opt in "-i":
            db_ip = arg
        elif opt in "-p":
            db_port = arg
        elif opt in "-r":
            deleteDB = True

    print ('db_ip  is: ', db_ip)
    print ('db_port is: ', db_port)
    print ('driver for rethinkdb')
    print ('DB Host ' + db_ip + ':' + db_port)
    db_name = 'dragonflow'

    if (deleteDB):
        cnt = 100
        while (cnt > 0):
            try:
                R.connect(host=db_ip, port=int(db_port)).repl()
                cnt = 0
            except Exception as e:
                if cnt == 0:
                    raise e
                else:
                    cnt -= 1
                    time.sleep(1)
                    continue
        all_databases = R.db_list().run()
        for database in all_databases:
            if database == db_name:
                print ('Database ' + db_name +
                   ' exist, delete')
                R.db_drop(db_name).run()
        sys.exit(0)

    print ('table names are: ', db_table)
    cnt = 100
    while (cnt > 0):
        try:
            R.connect(host=db_ip, port=int(db_port)).repl()
            cnt = 0
        except Exception as e:
            if cnt == 0:
                raise e
            else:
                cnt -= 1
                time.sleep(1)
                continue

    db_exist = 0
    all_databases = R.db_list().run()
    for database in all_databases:
        if database == db_name:
            print ('Database ' + db_name +
                   ' already exist, do not create')
            #R.db_drop(db_name).run()
            db_exist = 1
    if db_exist == 0:
        print ('Creating Database: ' + db_name)
        R.db_create(db_name).run()

    all_tables = R.db(db_name).table_list().run()

    for table in db_table:
        if len(all_tables) == 0:
            print ('Creating Table: ' + table +
                  ' in database: ' + db_name)
            R.db(db_name).\
                table_create(table, primary_key='name').run()
        else:
            for _table in all_tables:
                if _table in db_table:
                    print ('Table ' + table +
                          ' already exist in database '
                          + db_name + '...cleaning up...')
                else:
                    #R.db(db_name).table_drop(table).run()
                    print ('Creating Table: ' + table +
                          ' in database: ' + db_name)
                    R.db(db_name).\
                        table_create(table, primary_key='name').run()
                    break

if __name__ == "__main__":
    main(sys.argv[1:])
