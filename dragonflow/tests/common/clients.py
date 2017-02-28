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

import functools
import os

from keystoneauth1 import identity
from keystoneauth1 import session
from neutronclient.v2_0 import client
from novaclient import client as novaclient
import os_client_config


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


def get_neutron_client_from_cloud_config():
    return get_client_from_cloud_config(client.Client)


def get_nova_client_from_cloud_config():
    return get_client_from_cloud_config(
        functools.partial(novaclient.Client, '2')
    )


def get_client_from_cloud_config(client):
    creds = credentials()
    return get_client(
        client,
        auth_url=creds['auth_url'] + '/v3',
        username=creds['username'],
        password=creds['password'],
        project_name=creds['project_name'],
        project_domain_id=creds['project_domain_id'],
        user_domain_id=creds['user_domain_id'],
    )


def get_neutron_client_from_env():
    return get_client_from_env(client.Client)


def get_nova_client_from_env():
    return get_client_from_env(functools.partial(novaclient.Client, '2'))


def get_client_from_env(client):
    return get_client(
        client,
        auth_url=os.environ['OS_AUTH_URL'],
        username=os.environ['OS_USERNAME'],
        password=os.environ['OS_PASSWORD'],
        project_name=os.environ['OS_PROJECT_NAME'],
        project_domain_name=os.environ['OS_PROJECT_DOMAIN_NAME'],
        user_domain_name=os.environ['OS_USER_DOMAIN_NAME'],
    )


def get_neutron_client(**kwargs):
    return get_client(client.Client, **kwargs)


def get_client(client, **kwargs):
    auth = identity.Password(**kwargs)
    sess = session.Session(auth=auth)
    neutron = client(session=sess)
    return neutron
