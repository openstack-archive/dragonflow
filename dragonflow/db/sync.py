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

from dragonflow.db import db_store2 as db_store
from dragonflow.db.models import mixins

ALL_TOPICS = object()
UPDATE_PERIOD = 10


class Sync(object):
    '''Class that keeps local cache in sync with the NB database'''

    def __init__(self, nb_api, update_cb, delete_cb):
        self._nb_api = nb_api
        self._update_cb = update_cb
        self._delete_cb = delete_cb
        self._db_store = db_store.get_instance()
        self._models = []
        self._topics = set()
        self._sync_keys = {}

    def add_model(self, model):
        self._models.append(model)

    def add_topic(self, topic):
        '''Adds an new topic to watch in the NB database and pulls the new
           objects.
        '''
        self._topics.add(topic)
        self.sync()

    def remove_topic(self, topic):
        '''Removes a watched topic and drops all its objects from the
           controller.
        '''
        self._topics.remove(topic)
        self.sync()

    def sync(self, full=False, topics=None):
        '''Syncs all the models for all relevant topics.

           The state of the Sync class holds pairs of <model, topic> and the
           time that pair was last synced.

           Upon each sync we construct the list of pairs we need to have synced
           and compare to the list of pairs we have synced in the past.

           full parameter can be set to True to ignore the current state sync
           everything from scratch.
        '''
        if topics is not None:
            self._topics = set(topics)

        needed = self._needed_sync_keys()
        current = set(self._sync_keys.keys())

        for model, topic in (current - needed):
            self._delete(model, topic)

        now = time.time()
        for key in current.intersection(needed):
            if full or (now - self._sync_keys[key]) > UPDATE_PERIOD:
                model, topic = key
                self._update(model, topic)

        for model, topic in (needed - current):
            self._update(model, topic)

    def _needed_sync_keys(self):
        result = set()
        for model in self._models:
            if issubclass(model, mixins.Topic):
                result |= set((model, t) for t in self._topics)
            else:
                result.add((model, ALL_TOPICS))
        return result

    def _update(self, model, topic):
        key = model, topic

        if topic == ALL_TOPICS:
            topic = None

        local_ids = set(self._db_store.get_keys_by_topic(model, topic))

        nb_objects = {o.id: o for o in self._nb_api.get_all(model, topic)}
        nb_ids = set(nb_objects.keys())

        deleted_ids = local_ids - nb_ids

        for obj_id in deleted_ids:
            self._delete_cb(model(id=obj_id))

        for obj in nb_objects.values():
            if obj.id not in deleted_ids:
                self._update_cb(obj)

        self._sync_keys[key] = time.time()

    def _delete(self, model, topic):
        local_objs = tuple(self._db_store.get_all_by_topic(model, topic))
        for obj in local_objs:
            self._delete_cb(obj)

        del self._sync_keys[(model, topic)]
