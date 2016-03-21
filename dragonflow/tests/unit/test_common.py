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

from dragonflow.common import utils
from dragonflow.tests import base as tests_base


class TestRetryFunc(tests_base.BaseTestCase):

    def test_retry_wrapper_succeeds(self):
        @utils.wrap_func_retry(max_retries=10)
        def some_method():
            pass

        some_method()

    def test_retry_wrapper_reaches_limit(self):

        @utils.wrap_func_retry(max_retries=10,
                               _errors=[ValueError])
        def some_method(res):
            res['result'] += 1
            raise ValueError()

        res = {'result': 0}
        self.assertRaises(ValueError, some_method, res)
        self.assertEqual(11, res['result'])

    def test_retry_wrapper_exception_checker(self):

        def exception_checker(exc):
            return isinstance(exc, ValueError) and exc.args[0] < 5

        @utils.wrap_func_retry(max_retries=10,
                               exception_checker=exception_checker)
        def some_method(res):
            res['result'] += 1
            raise ValueError(res['result'])

        res = {'result': 0}
        self.assertRaises(ValueError, some_method, res)
        # our exception checker should have stopped returning True after 5
        self.assertEqual(5, res['result'])

    @mock.patch('dragonflow.common.utils.LOG')
    def test_retry_wrapper_non_error_not_logged(self, mock_log):
        # Tests that if the retry wrapper hits a target error (raised from the
        # wrapped function), then that exception is reraised but not logged.

        @utils.wrap_func_retry(max_retries=5,
                           _errors=[ValueError])
        def some_method():
            raise AttributeError('test')

        self.assertRaises(AttributeError, some_method)
        self.assertFalse(mock_log.called)
