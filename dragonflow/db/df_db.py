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

import sys

from oslo_config import cfg
from oslo_utils import importutils

from neutron.common import config as common_config

from dragonflow.common import common_params

cfg.CONF.register_opts(common_params.df_opts, 'df')

db_tables = ['lport', 'lswitch', 'lrouter', 'chassis', 'secgroup', 'tunnel_key']

def main():
    common_config.init(['--config-file', '/etc/neutron/neutron.conf'])
    db_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
    db_driver = db_driver_class()
    db_driver.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                         db_port=cfg.CONF.df.remote_db_port)
    action = sys.argv[1]

    if action == 'ls':
        if len(sys.argv) == 2:
            print (' ')
            print ('DB Tables')
            print ('----------')
            for table in db_tables:
                print table
            print(' ')
            return
        table = sys.argv[2]
        keys = db_driver.get_all_keys(table)
        print (' ')
        print ('Keys for table ' + table)
        print ('-------------------------------------------------------------------')
        for key in keys:
            print key
        print (' ')

    if action == 'get':
        table = sys.argv[2]
        key = sys.argv[3]
        value = db_driver.get_key(table, key)
        print (' ')
        print ('Table = ' + table + ' , Key = ' + key)
        print ('-------------------------------------------------------------------')
        print value
        print (' ')


if __name__ == "__main__":
    main()
