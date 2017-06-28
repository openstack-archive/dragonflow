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

import os
import random
import string

from oslo_log import log

from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as ctrl_const
from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.tests import base
from dragonflow.tests.common import app_testing_objects as test_objects
from dragonflow.tests.common import clients
from dragonflow.tests.common import constants as const
from dragonflow.tests.common import utils


LOG = log.getLogger(__name__)
_publisher = None


class DFTestBase(base.BaseTestCase):

    def setUp(self):
        super(DFTestBase, self).setUp()
        if os.environ.get('DF_FULLSTACK_USE_ENV'):
            try:
                self.neutron = clients.get_neutron_client_from_env()
            except KeyError as e:
                message = ('Cannot find environment variable %s. '
                           'Have you sourced openrc?')
                LOG.error(message, e.args[0])
                self.fail(message % e.args[0])
        else:
            self.neutron = clients.get_neutron_client_from_cloud_config()
        self.neutron.format = 'json'

        # NOTE: Each env can only have one default subnetpool for each
        # IP version.
        if not self.get_default_subnetpool():
            self.create_default_subnetpool()

        df_utils.config_parse()
        self.conf = cfg.CONF.df
        self.integration_bridge = self.conf.integration_bridge

        self.nb_api = api_nb.NbApi.get_instance(False)

        self.mgt_ip = self.conf.management_ip
        self.__objects_to_close = []
        self.addCleanup(self._close_stored_objects)

        self.vswitch_api = utils.OvsTestApi(self.mgt_ip)
        self.vswitch_api.initialize(self.nb_api)

        if cfg.CONF.df.enable_selective_topology_distribution:
            self.start_subscribing()

        if cfg.CONF.df.enable_df_pub_sub:
            self._publish_log_event('started')
            self.addCleanup(self._publish_log_event, 'finished')

    def _publish_log_event(self, event):
        global _publisher
        if _publisher is None:
            _publisher = self.get_publisher(port=23456)

        test_name = self.id()
        _publisher.send_event(
            db_common.DbUpdate(
                action=ctrl_const.CONTROLLER_LOG,
                table='testing',
                key=test_name,
                value='\n{0} {1}\n'.format(test_name, event),
            ),
        )

    def _get_publisher(self, pubsub_driver_name):
        pub_sub_driver = df_utils.load_driver(
            pubsub_driver_name,
            df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publisher = pub_sub_driver.get_publisher()
        publisher.initialize()
        return publisher

    def get_publisher(self, port=None):
        if cfg.CONF.df.pub_sub_use_multiproc:
            pubsub_driver_name = cfg.CONF.df.pub_sub_multiproc_driver
        else:
            pubsub_driver_name = cfg.CONF.df.pub_sub_driver
        if port is not None:
            cfg.CONF.set_override('publisher_port', port, group='df')
        return self._get_publisher(pubsub_driver_name)

    def check_app_loaded(self, app_name):
        apps_list = cfg.CONF.df.apps_list
        if app_name in apps_list:
            return True
        return False

    def _close_stored_objects(self):
        while self.__objects_to_close:
            close_func = self.__objects_to_close.pop()
            close_func()

    def get_default_subnetpool(self):
        default_subnetpool = None
        subnetpool_filter = {'is_default': True,
                             'ip_version': 4}
        subnetpools = self.neutron.list_subnetpools(
            **subnetpool_filter).get('subnetpools')
        if subnetpools:
            default_subnetpool = subnetpools[0]

        return default_subnetpool

    def create_default_subnetpool(self):
        default_subnetpool = {'prefixes': ['10.0.0.0/8'],
                              'name': 'default_subnetpool_v4',
                              'is_default': True,
                              'default_prefixlen': 24}
        self.neutron.create_subnetpool(
            body={'subnetpool': default_subnetpool})

    def store(self, obj, close_func=None):
        close_func = close_func if close_func else obj.close
        self.__objects_to_close.append(close_func)
        return obj

    def start_subscribing(self):
        self._topology = self.store(
            test_objects.Topology(self.neutron, self.nb_api))
        subnet = self._topology.create_subnet(cidr="192.168.200.0/24")
        port = subnet.create_port()
        utils.wait_until_true(
            lambda: port.name is not None,
            timeout=const.DEFAULT_RESOURCE_READY_TIMEOUT,
            exception=Exception('Port was not created')
        )

    def stop_subscribing(self):
        if hasattr(self, '_topology'):
            self._topology.close()

    def _create_random_string(self, length=16):
        alphabet = string.printable
        return ''.join([random.choice(alphabet) for _ in range(length)])
