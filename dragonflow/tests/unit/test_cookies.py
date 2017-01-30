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

import collections
import mock

from dragonflow.common import exceptions
from dragonflow.controller.common import cookies
from dragonflow.tests import base as tests_base


class TestCookies(tests_base.BaseTestCase):
    @mock.patch.object(cookies, '_cookies_used_bits',
                       collections.defaultdict(int))
    @mock.patch.object(cookies, '_cookies', {})
    def test_register_cookie_bits(self):
        _cookies = cookies._cookies
        used_bits = cookies._cookies_used_bits
        cookies.register_cookie_bits('test1', 3)
        cookies.register_cookie_bits('test2', 5)
        cookies.register_cookie_bits('test3', 5, True, 'app')
        cookies.register_cookie_bits('test4', 4, True, 'app')
        self.assertEqual(cookies.CookieBitPair(0, 0x7),
                         _cookies[(cookies.GLOBAL_APP_NAME, 'test1')])
        self.assertEqual(cookies.CookieBitPair(3, 0x1f << 3),
                         _cookies[(cookies.GLOBAL_APP_NAME, 'test2')])
        self.assertEqual(cookies.CookieBitPair(32, 0x1f << 32),
                         _cookies[('app', 'test3')])
        self.assertEqual(cookies.CookieBitPair(37, 0xf << (32 + 5)),
                         _cookies[('app', 'test4')])
        self.assertEqual(8, used_bits[cookies.GLOBAL_APP_NAME])
        self.assertEqual(9, used_bits['app'])

    @mock.patch.object(cookies, '_cookies_used_bits',
                       collections.defaultdict(int))
    @mock.patch.object(cookies, '_cookies', {})
    def test_register_and_get_cookies(self):
        cookies.register_cookie_bits('test1', 3)
        cookies.register_cookie_bits('test2', 5)
        cookies.register_cookie_bits('test3', 5, True, 'app')
        cookies.register_cookie_bits('test4', 4, True, 'app')
        self.assertEqual((3, 0x7), cookies.get_cookie('test1', 3))
        self.assertEqual((5 << 3, 0x1f << 3), cookies.get_cookie('test2', 5))
        self.assertEqual((10 << 32, 0x1f << 32),
                         cookies.get_cookie('test3', 10,
                                            is_local=True, app_name='app'))
        self.assertEqual((13 << (32 + 5) | 10 << 32, 0xf << 37 | 0x1f << 32),
                         cookies.get_cookie('test4', 13,
                                            old_cookie=10 << 32,
                                            old_mask=0x1f << 32,
                                            is_local=True, app_name='app'))
        cookie, mask = cookies.get_cookie('test1', 2)
        self.assertEqual((2, 0x7),
                         cookies.get_cookie('test1', 3, cookie, mask))

    @mock.patch.object(cookies, '_cookies_used_bits',
                       collections.defaultdict(int))
    @mock.patch.object(cookies, '_cookies', {})
    def test_register_cookie_bits_errors(self):
        self.assertRaises(TypeError,
                          cookies.register_cookie_bits, 't1', 3, True)
        self.assertRaises(exceptions.OutOfCookieSpaceException,
                          cookies.register_cookie_bits, 't1', 33)
        self.assertRaises(exceptions.OutOfCookieSpaceException,
                          cookies.register_cookie_bits, 't1', 33, True, 'app')
        cookies.register_cookie_bits('t1', 10)
        cookies.register_cookie_bits('t1', 10, True, 'app')
        self.assertRaises(exceptions.OutOfCookieSpaceException,
                          cookies.register_cookie_bits, 't2', 23)
        self.assertRaises(exceptions.OutOfCookieSpaceException,
                          cookies.register_cookie_bits, 't2', 23, True, 'app')

    @mock.patch.object(cookies, '_cookies_used_bits',
                       collections.defaultdict(int))
    @mock.patch.object(cookies, '_cookies', {})
    def test_get_cookies_errors(self):
        cookies.register_cookie_bits('test1', 3)
        cookies.register_cookie_bits('test2', 5)
        cookies.register_cookie_bits('test3', 5, True, 'app')
        cookies.register_cookie_bits('test4', 4, True, 'app')
        self.assertRaises(TypeError,
                          cookies.get_cookie, 'test3', 3, is_local=True)
        self.assertRaises(exceptions.CookieOverflowExcpetion,
                          cookies.get_cookie, 'test1', 9)
        self.assertRaises(exceptions.MaskOverlapException,
                          cookies.get_cookie, 'test2', 9, 0, 0x8)
