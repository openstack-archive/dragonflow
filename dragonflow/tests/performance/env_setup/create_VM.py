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

from novaclient import client as novaclient
import os_client_config
import sys


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


def create_vm(vmName, networkName, computeName):
    creds = credentials()
    print(creds)
    auth_url = creds['auth_url'] + "/v2.0"
#   auth_url = "http://10.100.100.43:5000/v2.0"
    nova = novaclient.Client('2', creds['username'], creds['password'],
        'demo', auth_url)
    image = nova.images.find(name="iPerfServer")
#   get the flavor
    flavor = nova.flavors.find(name="m1.small")
    network = nova.networks.find(label=networkName)
    nics = [{'net-id': network.id}]
#   computeName not empty (removes spaces)
    if computeName.strip():
        nova.servers.create(name=vmName, image=image.id, key_name="ssh-key",
            flavor=flavor.id, nics=nics, availability_zone=computeName.strip())
    else:
        nova.servers.create(name=vmName, image=image.id, key_name="ssh-key",
            flavor=flavor.id, nics=nics)


if __name__ == '__main__':
    if len(sys.argv) == 3:
        create_vm(sys.argv[1], sys.argv[2], "")
    if len(sys.argv) == 4:
        create_vm(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit()
