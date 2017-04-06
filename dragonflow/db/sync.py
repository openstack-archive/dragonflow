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
from dragonflow.db import db_store
from dragonflow.db.models import mixins


def _make_dict(iterable):
    return {o.id: o for o in iterable}


class Sync(object):
    '''Class that keeps local cache in sync with the NB database'''

    def __init__(self, nb_api, update_cb, delete_cb, selective=True):
        self._nb_api = nb_api
        self._update_cb = update_cb
        self._delete_cb = delete_cb
        self._db_store = db_store.get_instance()
        self._topics = set()
        self._selective = selective
        self._models = []

    def add_model(self, model):
        self._models.append(model)

    def add_topic(self, topic):
        '''Adds an new topic to watch in the NB database and pulls the new
           objects.
        '''
        if not self._selective or topic in self._topics:
            return

        # Sync here, new objects might rely on objects just added
        self.sync()

        for model in self._models:
            if not issubclass(model, mixins.Topic):
                continue

            for nb_obj in self._nb_api.get_all(model, topic):
                self._update_cb(nb_obj)

        self._topics.add(topic)

    def remove_topic(self, topic):
        '''Removes a watched topic and drops all its objects from the
           controller.
        '''
        if not self._selective or topic not in self._topics:
            return

        self._topics.remove(topic)

        # Reverse the model order, dependent objects deleted first
        for model in reversed(self._models):
            if not issubclass(model, mixins.Topic):
                continue

            cached_objs = list(self._db_store.get_all_by_topic(model, topic))
            for cached_obj in cached_objs:
                self._delete_cb(cached_obj)

    def sync(self):
        '''Syncs all the models for all relevant topics.
        '''
        for model in self._models:
            self._update_model(model)

        # Reverse order when deleting objects
        for model in reversed(self._models):
            self._cleanup_model(model)

    def _update_model(self, model):
        if not self._selective or not issubclass(model, mixins.Topic):
            desired = self._nb_api.get_all(model)
            self._update_objects(desired)
        else:
            for topic in self._topics:
                desired = self._nb_api.get_all(model, topic)
                self._update_objects(desired)

    def _update_objects(self, desired):
        for o in desired:
            self._update_cb(o)

    def _cleanup_model(self, model):
        if not self._selective or not issubclass(model, mixins.Topic):
            desired = self._nb_api.get_all(model)
            present = self._db_store.get_all(model)
            self._cleanup_objects(desired, present)
        else:
            present_all = self._db_store.get_all(model)
            present_by_topic = {}
            for o in present_all:
                present_by_topic.setdefault(o.topic, []).append(o)

            for topic in self._topics:
                # FIXME (dimak) can be avoided, we do this once in
                # _update_model for the exact same topics/models.
                # Maybe we can pass on the result somehow.
                desired = self._nb_api.get_all(model, topic)
                present = present_by_topic.pop(topic, [])
                self._cleanup_objects(desired, present)

            for objects in present_by_topic.values():
                for o in objects:
                    self._delete_cb(o)

    def _cleanup_objects(self, desired, present):
        desired = _make_dict(desired)
        present = _make_dict(present)

        desired_ids = set(desired.keys())
        present_ids = set(present.keys())

        for deleted_id in present_ids.difference(desired_ids):
            self._delete_cb(present[deleted_id])
