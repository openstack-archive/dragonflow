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

#!/usr/bin/python

from dragonflow.db.drivers import ramcloud_db_driver
import getopt
import sys


def main(argv):
    db_ip = ''
    db_port = ''
    try:
        opts, args = getopt. \
            getopt(sys.argv[1:],
                   'd:t:i:p:', ['-t val', '-i val', '-p val'])
    except getopt.GetoptError:
        print ('table_setup_ramcloud.py '
               ' -t <table_name>,<table_name>..<table_name>'
               ' -i <db_ip> -p <db_port>')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print ('table_setup_ramcloud.py '
                   '-t <table_name> -i <db_ip> -p <db_port>')
            sys.exit()
        elif opt in "-t":
            db_table = arg.split(',')
        elif opt in "-i":
            db_ip = arg
        elif opt in "-p":
            db_port = arg
    print ('table names are: ', db_table)
    print ('db_ip  is: ', db_ip)
    print ('db_port is: ', db_port)

    print ('driver for RamCloud')
    print ('DB Host ' + db_ip + ':' + db_port)
    print ('Creating Tables: ', db_table)
    client = ramcloud_db_driver.RamCloudDbDriver()
    client.initialize(db_ip, db_port)
    client.create_tables(db_table)

if __name__ == "__main__":
    main(sys.argv[1:])
