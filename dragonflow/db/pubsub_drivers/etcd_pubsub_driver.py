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

from oslo_config import cfg
from oslo_log import log as logging

from dragonflow.common import exceptions
from dragonflow.db import pub_sub_api

LOG = logging.getLogger(__name__)

SUPPORTED_TRANSPORTS = set(['tcp', 'epgm'])


class EtcdPubSub(pub_sub_api.PubSubApi):
    def __init__(self):
        super(EtcdPubSub, self).__init__()
        transport = cfg.CONF.df.publisher_transport
        if transport not in SUPPORTED_TRANSPORTS:
            message = ("etcd_pub_sub: Unsupported publisher_transport value "
                       "%(transport)s, expected %(expected)s")
            LOG.error(message, {
                'transport': transport,
                'expected': SUPPORTED_TRANSPORTS
            })
            raise exceptions.UnsupportedTransportException(transport=transport)
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
        self.client = etcd.Client(host=cfg.CONF.df.remote_db_ip,
                                  port=cfg.CONF.df.remote_db_port)


class TopicThread(threading.Thread):
    # TODO
    def __init__(self, ):
        self.daemon = True
        self.target = self.startWatch
        super(TopicThread, self).__init__()

    def startWatch(etcdClient, topic=None, stop):
        if topic: # and self.running:
            self.w = etcd3gw.watch.Watcher(self, key, callback, **kwargs)
            for event, cancel in etcdClient.watch(topic):
                print("topic thread got event = {}".format(event))
                # TODO handle event
                pass

    def stop(self):
        self.w.stop()


class EtcdSubscriberAgent(pub_sub_api.SubscriberApi):
    def __init__(self):
        self.topic_list = []
        self.topic_threads = []
        self.uri_list = []
        super(EtcdSubscriberAgent, self).__init__()

    def initialize(self, callback):
        self.db_changes_callback = callback
        self.stop_event = threading.Event()
        # self.daemon = threading.Thread(target=self.run)
        # self.daemon.daemon = True

    def connect(self):
        """Connect to the publisher"""
        self.topic_threads = []
        self.client = self.etcd3gw.Client(host=cfg.CONF.df.remote_db_ip,
                                     port=cfg.CONF.df.remote_db_port)
        for topic in self.topic_list:
            # start topic threads
            self.topic_threads.append(TopicThread(
                args=self.stop_event,
                kwargs={'topic':topic}))

    def deamonize(self):
        # Start watching
        self.running = True
        self.connect()
        for thread in topic_threads:
            thread.start()

    def close():
        self.running = False
        for topic in self.topic_threads:
            # TODO verify stop. Wait on all threads?
            self.stop_event.set()
            pass
        self.topic_threads = []

    def register_topic(self, topic):
        LOG.info('Register topic %s', topic)
        if topic not in self.topic_list:
            self.topic_list.append(topic)
            if self.running:
                self._start_topic_watch(topic)
            return True
        return False

    def unregister_topic(self, topic):
        LOG.info('Unregister topic %s', topic)
        self.topic_list.remove(topic)
        if self.running:
            self._stop_topic_watch(topic)

    def _stop_topic_watch(self, topic):
        #TODO
        pass

    def _start_topic_watch(self, topic):
        #TODO handle cancel
        if topic:
            for event, cancel in self.client.watch(topic):
                # TODO handle formatting. change to watcher
                print("event = {}".format(event))
                self.db_changes_callback(
                    event['table'],
                    event['key'],
                    event['action'],
                    event['value'],
                    event['topic'],
                )
                pass

    def run(self):
        # Not needed
        pass
