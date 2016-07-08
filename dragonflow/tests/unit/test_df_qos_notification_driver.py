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

"""Unit testing for QoS notification driver."""

import six


class stub_wrap_db_lock(object):
    def __init__(self, type):
        pass

    def __call__(self, f):
        @six.wraps(f)
        def stub_wrap_db_lock(*args, **kwargs):
            f(*args, **kwargs)
        return stub_wrap_db_lock


import mock

# mock.patch must before import mech_driver, because mech_driver will load the
# lockedobjects_db
mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
           stub_wrap_db_lock).start()
from dragonflow.db.neutron import versionobjects_db as version_db
from dragonflow.neutron.services.qos.notification_drivers import \
    df_qos_notification_driver
from neutron.api.rpc.callbacks import events as rpc_events
from neutron import manager
from neutron.tests import base


class TestDFQosNotificationDriver(base.BaseTestCase):

    """Testing dragonflow mechanism driver."""

    def setUp(self):
        super(TestDFQosNotificationDriver, self).setUp()
        self.driver = df_qos_notification_driver.\
            DFQosServiceNotificationDriver()
        self.driver.nb_api = mock.Mock()
        self.dbversion = 0
        version_db._create_db_version_row = mock.Mock(
            return_value=self.dbversion)
        version_db._update_db_version_row = mock.Mock(
            return_value=self.dbversion)
        version_db._delete_db_version_row = mock.Mock()

    def test_create_policy(self):
        qos_policy = self._get_qos_policy(None, rpc_events.CREATED)
        self.driver.create_policy(fakecontext, qos_policy)
        self.driver.nb_api.create_qos_policy.assert_called_with(
            123, 456, name='qos1', rules=[], version=self.dbversion)

    def test_update_policy(self):
        manager.NeutronManager.get_service_plugins = mock.Mock(
            return_value=service_plugin)

        rules = {'id': 123,
                 'max_burst_kbps': 1000,
                 'max_kbps': 100,
                 'qos_policy_id': 123}

        qos_policy = self._get_qos_policy(rules, rpc_events.UPDATED)
        self.driver.update_policy(fakecontext, qos_policy)
        self.driver.nb_api.update_qos_policy.assert_called_with(
            123, 456, name='qos1', rules=rules, version=self.dbversion)

    def test_delete_policy(self):
        manager.NeutronManager.get_service_plugins = mock.Mock(
            return_value=service_plugin)

        qos_policy = self._get_qos_policy(None, rpc_events.DELETED)
        self.driver.delete_policy(fakecontext, qos_policy)
        self.driver.nb_api.delete_qos_policy.assert_called_with(123, 456)

    def _get_qos_policy(self, rules, event_type):
        if event_type == rpc_events.CREATED:
            qos_policy = {'id': 123,
                          'name': 'qos1',
                          'shared': False,
                          'tenant_id': 456}
        elif event_type == rpc_events.UPDATED:
            qos_policy = {'id': 123,
                          'name': 'qos1',
                          'rules': rules,
                          'shared': False,
                          'tenant_id': 456}
        elif event_type == rpc_events.DELETED:
            qos_policy = {'id': 123}

        return qos_policy


class QosPlugin(object):
    def __init__(self):
        pass

    def get_policy(self, context, policy_id):
        qos_policy = {'id': 123,
                      'tenant_id': 456,
                      'rules': {'max_kbps': 100, 'id': 123,
                                'max_burst_kbps': 1000, 'qos_policy_id': 123}}
        return qos_policy


class ServicePlugin(object):
    def __init__(self):
        pass

    def get(self, plugin_name):
        return qos_plugin


class SessionTransaction(object):
    def __init__(self, session, parent=None, nested=False):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        pass


class FakeSession(object):
    def __init__(self):
        pass

    def begin(self, subtransactions=True):
        return sessiontransaction


class FakeContext(object):
    """To generate context for testing purposes only."""
    def __init__(self):
        self._session = fakesession

    @property
    def session(self):
        return self._session


service_plugin = ServicePlugin()
qos_plugin = QosPlugin()
fakesession = FakeSession()
fakecontext = FakeContext()
sessiontransaction = SessionTransaction(fakesession, None, False)
