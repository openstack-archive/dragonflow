#!/usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sys
import os_client_config
from oslo_config import cfg
from neutronclient.neutron import client
from dragonflow.common import common_params

cfg.CONF.register_opts(common_params.df_opts, 'df')


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)

def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()

class UpdateQuota():
    def __init__(self):
        creds = credentials()
        tenant_name = creds['project_name']
        auth_url = creds['auth_url'] + "/v2.0"
        self.neutron = client.Client('2.0', username=creds['username'],
             password=creds['password'], auth_url=auth_url,
             tenant_name=tenant_name)

    def fix(self):
        body = {'floatingip': 100,
                'network': 1000,
                'security_group': 200,
                'router': 1000,
                'port': 1000}
        self.neutron.update_quota('admin', {"quota": body})
        result = self.neutron.show_quota('admin')
        print('New quota', result)

def main():
    fix = UpdateQuota()
    fix.fix()

if __name__ == '__main__':
    print("Fixing openstack quotas")
    sys.exit(main())

