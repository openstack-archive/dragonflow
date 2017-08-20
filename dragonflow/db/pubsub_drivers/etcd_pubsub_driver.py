# All Rights Reserved.
#
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

import etcd3gw
import threading

from oslo_config import cfg
from oslo_log import log as logging

from dragonflow.common import exceptions
from dragonflow.db import pub_sub_api

from dragonflow.db import api_nb


LOG = logging.getLogger(__name__)

PUBSUB_DB_PREFIX = "pubsub"


class EtcdPubSub(pub_sub_api.PubSubApi):
    def __init__(self):
        super(EtcdPubSub, self).__init__()
        self.subscriber = EtcdSubscriberAgent()
        self.publisher = EtcdPublisherAgent()

    def get_publisher(self):
        return self.publisher

    def get_subscriber(self):
        return self.subscriber


class EtcdPublisherAgent(pub_sub_api.PublisherAgentBase):
    def __init__(self):
        super(EtcdPublisherAgent, self).__init__()
        self.client = None

    def _connect(self):
        self.client = etcd3gw.client(host=cfg.CONF.df.remote_db_ip,
                                     port=cfg.CONF.df.remote_db_port)
        self.driver = api_nb.NbApi.get_instance().driver

    def _send_event(self, data, topic):
        topic_prefix = "{}/{}".format(PUBSUB_DB_PREFIX, topic)
        topic_unique_key = self.driver.allocate_unique_key(topic_prefix)
        self.driver.create_key(topic_prefix, topic_unique_key, data)

    def close(self):
        # TODO
        pass

    def initialize(self):
        # TODO
        pass


class EtcdSubscriberAgent(pub_sub_api.SubscriberApi):
    def __init__(self):
        self.topic_list = []
        self.topic_threads = []
        self.uri_list = []
        self.running = False
        super(EtcdSubscriberAgent, self).__init__()

    def initialize(self, callback):
        self.db_changes_callback = callback
        self.stop_event = threading.Event()

    def connect(self):
        """Connect to the publisher"""
        self.topic_threads = []
        self.client = etcd3gw.client(host=cfg.CONF.df.remote_db_ip,
                                     port=cfg.CONF.df.remote_db_port)

    def _get_topic_thread(self, topic):
        topic_thread = threading.Thread(
            target=self._start_topic_watch,
            args=self.stop_event,
            kwargs={'topic': topic})
        return topic_thread

    def daemonize(self):
        # Start watching
        self.running = True
        self.connect()
        for thread in self.topic_threads:
            thread.start()

    def close(self):
        # TODO: stop threads
        self.running = False

    def register_topic(self, topic):
        LOG.info('Register topic %s', topic)
        if topic not in self.topic_list:
            self.topic_list.append(topic)
            topic_thread = self._get_topic_thread(topic)
            self.topic_threads.append(topic_thread)
            if self.running:
                topic_thread.start()
            return True
        return False

    def unregister_topic(self, topic):
        LOG.info('Unregister topic %s', topic)
        self.topic_list.remove(topic)
        self.topic_threads.remove
        if self.running:
            self._stop_topic_watch(topic)

    def _stop_topic_watch(self, topic):
        # TODO: 1. find topic thread
        # 2. stop it
        # 3. Remove it
        pass

    def handle_event(self, event):
        # TODO not working.
        print("event = {}".format(event))
        self.db_changes_callback(
            event['table'],
            event['key'],
            event['action'],
            event['value'],
            event['topic'],
        )

    def _start_topic_watch(self, topic):
        # TODO handle cancel
        if topic:
            topic_watch_prefix = "{}/{}".format(PUBSUB_DB_PREFIX, topic)
            events, cancel = self.client.watch_prefix(topic_watch_prefix)
            for event in events:
                self.handle_event(event)
            # self.w = etcd3gw.watch.Watcher(self, topic, self.handle_event)

    def register_listen_address(self, uri):
        # TODO
        pass

    def unregister_listen_address(self, topic):
        # TODO
        pass

    def run(self):
        # Not needed
        pass

    # TODO these method ar mandatory. Add them ot the interface
    def set_subscriber_for_failover(self, sub, callback):
        pass

    def register_hamsg_for_db(self):
        pass

    def process_ha(self):
        pass
