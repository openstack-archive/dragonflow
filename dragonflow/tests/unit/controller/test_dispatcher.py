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

import mock

from dragonflow.common import exceptions
from dragonflow.controller import dispatcher
from dragonflow.tests import base as tests_base


class FakeAppWithException(object):

    def __init__(self, name):
        self.name = name

    def fake_handler(self):
        raise Exception("The exception from %s" % self.name)


class TestAppDispatcher(tests_base.BaseTestCase):

    def setUp(self):
        super(TestAppDispatcher, self).setUp()
        self.dispatcher = dispatcher.AppDispatcher("", "")

    def test_dispatch_with_exception(self):
        fake_app = mock.MagicMock()
        capture_e = None
        self.dispatcher.apps = [FakeAppWithException('fake1'),
                                FakeAppWithException('fake2'),
                                fake_app]
        try:
            self.dispatcher.dispatch('fake_handler')
        except exceptions.DFMultipleExceptions as e:
            capture_e = e
        finally:
            self.assertTrue(capture_e)
            self.assertEqual(2, len(capture_e.inner_exceptions))
            error_msg = str(capture_e)
            self.assertIn("The exception from fake1", error_msg)
            self.assertIn("The exception from fake2", error_msg)
            self.assertTrue(fake_app.fake_handler.called)
