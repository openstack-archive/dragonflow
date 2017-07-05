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

from dragonflow.db import api_nb
from dragonflow.db import db_store
import dragonflow.db.model_framework as mf
from dragonflow.db.models import mixins
from dragonflow.db import sync
from dragonflow.tests import base as tests_base
from dragonflow.tests.common import utils


@mf.register_model
@mf.construct_nb_db_model
class TopiclessModel(mf.ModelBase):
    table_name = 'topicless'


@mf.register_model
@mf.construct_nb_db_model
class TopicModel1(mf.ModelBase, mixins.Topic):
    table_name = 'topic1'


@mf.register_model
@mf.construct_nb_db_model
class TopicModel2(mf.ModelBase, mixins.Topic):
    table_name = 'topic2'


# Fixtures
topicless_a = TopiclessModel(id='topicless_a')
topicless_b = TopiclessModel(id='topicless_b')
topicless_c = TopiclessModel(id='topicless_c')

topic1_a = TopicModel1(id='topic1_a', topic='topic1')
topic1_b = TopicModel1(id='topic1_b', topic='topic1')
topic1_c = TopicModel1(id='topic1_c', topic='topic2')

topic2_a = TopicModel2(id='topic2_a', topic='topic1')
topic2_b = TopicModel2(id='topic2_b', topic='topic2')
topic2_c = TopicModel2(id='topic2_c', topic='topic3')


class TestSync(tests_base.BaseTestCase):
    def setUp(self):
        super(TestSync, self).setUp()
        self._db_store = db_store.get_instance()
        self._db_store.clear()

        self.nb_api = api_nb.NbApi(
            db_driver=mock.Mock(),
            use_pubsub=True,
            is_neutron_server=True
        )
        self.nb_api.publisher = mock.Mock()
        self.nb_api.enable_selective_topo_dist = True
        self._update = mock.Mock(side_effect=self._db_store.update)
        self._delete = mock.Mock(side_effect=self._db_store.delete)
        self.sync = sync.Sync(
            self.nb_api,
            self._update,
            self._delete,
        )
        self.sync.add_model(TopiclessModel)
        self.sync.add_model(TopicModel1)
        self.sync.add_model(TopicModel2)

    @utils.with_local_objects()
    @utils.with_nb_objects()
    def test_no_actions(self):
        self.sync.sync()
        self._update.assert_not_called()
        self._delete.assert_not_called()

    @utils.with_local_objects()
    @utils.with_nb_objects(topicless_a, topicless_b)
    def test_topicless_pulled(self):
        self.sync.sync()
        self.assertItemsEqual(
            (mock.call(topicless_a), mock.call(topicless_b)),
            self._update.mock_calls,
        )

    @utils.with_local_objects(topicless_a, topicless_b)
    @utils.with_nb_objects(topicless_b)
    def test_topicless_dropped(self):
        self.sync.sync()
        self._delete.assert_called_once_with(topicless_a)

    @utils.with_local_objects()
    @utils.with_nb_objects(topic1_a, topic1_b, topic1_c)
    def test_only_relevant_topic_pulled(self):
        self.sync.add_topic('topic1')
        self.assertItemsEqual(
            (mock.call(topic1_a), mock.call(topic1_b)),
            self._update.mock_calls,
        )

    @utils.with_local_objects()
    @utils.with_nb_objects(topicless_a, topic1_a, topic1_b, topic1_c,
                           topic2_a, topic2_b, topic2_c)
    def test_topic_removed(self):
        self.sync._topics = {'topic1', 'topic2', 'topic3'}
        self.sync.sync()

        self._update.reset_mock()
        self._delete.reset_mock()

        self.sync.remove_topic('topic2')
        self.assertItemsEqual(
            (mock.call(topic1_c), mock.call(topic2_b)),
            self._delete.mock_calls,
        )
