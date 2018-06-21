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

import six

from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.db import model_framework as mf
from dragonflow.db.models import mixins
from dragonflow.tests import base as tests_base


@mf.register_model
@mf.construct_nb_db_model
class ModelWithUniqueKey(mf.ModelBase, mixins.BasicEvents, mixins.UniqueKey):
    table_name = 'model_with_unique_key1'


def _bytes(*args):
    """
    Returns a byte array (bytes in py3, str in py2) of chr(b) for
    each b in args
    """
    if six.PY2:
        return "".join(chr(c) for c in args)
    # else: Python 3
    return bytes(args)


class TestUniqueKeyMixin(tests_base.BaseTestCase):
    def setUp(self):
        cfg.CONF.set_override('nb_db_class', '_dummy_nb_db_driver', group='df')
        super(TestUniqueKeyMixin, self).setUp()

    def test_allocate_unique_id(self):
        nb_api = api_nb.NbApi.get_instance()
        instance1 = ModelWithUniqueKey(id='instance1')
        nb_api.create(instance1)
        self.assertIsNotNone(instance1.unique_key)

    def test_unique_id_packed(self):
        instance = ModelWithUniqueKey(id='instance', unique_key=13)
        self.assertEqual(_bytes(0, 0, 0, 13),
                         instance.unique_key_packed)
        instance.unique_key = 0x12345678
        self.assertEqual(_bytes(0x12, 0x34, 0x56, 0x78),
                         instance.unique_key_packed)
