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

import time

from dragonflow.common import utils
from dragonflow.tests import base as tests_base


class TestRateLimiter(tests_base.BaseTestCase):
    def test_rate_limiter_oneshot(self):
        rate_limiter = utils.RateLimiter(3, 5)
        counter = 0
        for idx in range(5):
            if not rate_limiter():
                counter += 1
        self.assertEqual(3, counter)
        time.sleep(5)
        for idx in range(5):
            if not rate_limiter():
                counter += 1
        self.assertEqual(6, counter)

    def test_rate_limiter_continuus(self):
        rate_limiter = utils.RateLimiter(3, 5)
        counter = 0
        for idx in range(11):
            if not rate_limiter():
                counter += 1
            time.sleep(1)
        self.assertEqual(7, counter)
