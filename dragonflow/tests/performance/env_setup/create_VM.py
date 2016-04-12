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


def create_vm(networkName, computeName):
    creds = credentials()
    print(creds)
    auth_url = creds['auth_url'] + "/v2.0"
#   auth_url = "http://10.100.100.43:5000/v2.0"
    nova = novaclient.Client('2', creds['username'], creds['password'],
        'demo', auth_url)
#   print(nova.servers.list())
#   print(nova.flavors.list())
#   print(nova.images.list())
#   print(nova.keypairs.list())
    image = nova.images.find(name="cirros-0.3.4-x86_64")
#   print(image)
#   get the flavor
    flavor = nova.flavors.find(name="m1.tiny")
#   print(flavor)
    network = nova.networks.find(label=networkName)
#   print(network)
    nics = [{'net-id': network.id}]
#   print(nics)
#   computeName not empty (removes spaces)
    if computeName.strip():
        nova.servers.create(name='test', image=image.id,
            flavor=flavor.id, nics=nics, availability_zone=computeName.strip())
    else:
        nova.servers.create(name='test', image=image.id,
            flavor=flavor.id, nics=nics)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        create_vm(sys.argv[1], "")
    else:
        create_vm(sys.argv[1], sys.argv[2])
    sys.exit()
