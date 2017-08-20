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

# from dragonflow.common import exceptions
from dragonflow.db import pub_sub_api


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

    def initialize(self):
        super(EtcdPublisherAgent, self).__init__()
        self.client = etcd3gw.client(host=cfg.CONF.df.remote_db_ip,
                                     port=cfg.CONF.df.remote_db_port)

    def _send_event(self, data, topic):
        topic_prefix = "/{}/{}".format(PUBSUB_DB_PREFIX, topic)
        self.client.put(topic_prefix, data)

    def close(self):
        # TODO
        pass


class WatcherThread(threading.Thread):
    def __init__(self, etcd_client, kwargs):
        super(WatcherThread, self).__init__(target=self.startWatch,
                                            kwargs=kwargs)
        self.daemon = True
        self.client = etcd_client

    def startWatch(self, topic, handle_event):
        events, self._cancel = self.client.watch(topic)
        for event in events:
            handle_event(event)

    def cancel(self):
        self._cancel()


class EtcdSubscriberAgent(pub_sub_api.SubscriberApi):
    def __init__(self):
        self.topic_list = []
        self.uri_list = []
        self.running = False
        self.client = None
        super(EtcdSubscriberAgent, self).__init__()

    def initialize(self, callback):
        self.db_changes_callback = callback
        self.stop_event = threading.Event()
        self.client = etcd3gw.client(host=cfg.CONF.df.remote_db_ip,
                                     port=cfg.CONF.df.remote_db_port)

    def _get_topic_thread(self, topic):
        topic_thread = WatcherThread(
            etcd_client=self.client,
            kwargs={'topic': topic,
                    'handle_event': self.handle_event})
        return topic_thread

    def daemonize(self):
        # Start watching
        self.running = True
        for topic in self.topic_list:
            self.topic_list[topic].start()

    def close(self):
        # TODO: stop threads
        self.running = False
        for topic in self.topic_list:
            self._stop_topic_watch(self.topic_list[topic])

    def register_topic(self, topic):
        LOG.info('Register topic %s', topic)
        if topic not in self.topic_list:
            topic_thread = self._get_topic_thread(topic)
            self.topic_list["topic"] = topic_thread
            if self.running:
                topic_thread.start()
            return True
        return False

    def unregister_topic(self, topic):
        LOG.info('Unregister topic %s', topic)
        if self.running:
            self._stop_topic_watch(self.topic_list[topic])
        del self.topic_list[topic]

    def _stop_topic_watch(self, topic_thread):
        topic_thread.cancel()

    def handle_event(self, event):
        # TODO not working.
        LOG.info(" TFFF event = {}".format(event))
        self.db_changes_callback(
            event['table'],
            event['key'],
            event['action'],
            event['value'],
            event['topic'],
        )

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
