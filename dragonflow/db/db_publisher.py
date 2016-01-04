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

import eventlet
import msgpack
import multiprocessing
import zmq

from oslo_log import log as logging
from oslo_serialization import jsonutils
LOG = logging.getLogger(__name__)

eventlet.monkey_patch(all=True)


class PublisherAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_plugin=False):
        super(PublisherAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        #TODO(gampel) move to configuration
        self.plugin_updates_port = "8866"
        self.controllers_updates_port = "8867"

        self.pub_socket = None
        self.pool = eventlet.GreenPool()
        if is_plugin:
            self._queue = multiprocessing.Queue()
        else:
            self._queue = eventlet.queue.PriorityQueue()

        self.is_daemonize = False
        self.is_plugin = is_plugin

    def daemonize(self):
        self.is_daemonize = True
        self.pool.spawn(self.run)
        eventlet.sleep(0)

    def run(self):
        port = self.plugin_updates_port
        if not self.is_plugin:
            port = self.controllers_updates_port

        context = zmq.Context()
        socket = context.socket(zmq.PUB)

        #TODO(gampel) Handle address in use exception
        socket.bind("tcp://*:%s" % port)
        while True:
            event = None
            eventlet.sleep(0)
            try:
                event = self._queue.get()
            except eventlet.queue.Empty:
                eventlet.sleep(0.2)
            else:
                event_json = jsonutils.dumps(event.to_array())
                data = self.pack_message(event_json)
                socket.send_multipart([b"D", data])
                LOG.debug("sending %s" % event)
                eventlet.sleep(0)

    def pack_message(self, message):
        data = None
        try:
            data = msgpack.packb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return data

    def send_event(self, update):
        if self.is_daemonize:
            self._queue.put(update)
            eventlet.sleep(0)


def main():
    pubsub = PublisherAgent('127.0.0.1', None, None, is_plugin=True)
    pubsub.daemonize()
    while True:
        pubsub.send_event("t", "k", "a", "v")


if __name__ == "__main__":
    main()
