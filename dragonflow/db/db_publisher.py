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
from nanomsg import Socket, PUB

from oslo_log import log as logging

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


class PublisherAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_plugin=False):
        super(PublisherAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        #TODO(gampel) move to configuration
        self.plugin_updates_port = "8861"
        self.controllers_updates_port = "8862"

        self.pub_socket = None
        self._queue = eventlet.queue.Queue()
        self.is_daemonize = False
        self.is_plugin = is_plugin

    def daemonize(self):
        self.is_daemonize = True
        eventlet.spawn(self.run)
        eventlet.sleep(0)

    def run(self):
        self.pub_socket = Socket(PUB)
        port = self.plugin_updates_port

        if not self.is_plugin:
            port = self.controllers_updates_port
        self.endpoint = self.pub_socket.bind(
                "tcp://*:" + port)

        data = self.pack_message('sync')
        self.pub_socket.send(data)
        while True:
            event = None
            eventlet.sleep(0.1)
            try:
                event = self._queue.get(timeout=600)
            except eventlet.queue.Empty:
                self.pub_socket.send("sync")
                eventlet.sleep(0.2)
            else:
                data = self.pack_message(event)
                self.pub_socket.send(data)
                LOG.debug("sending %s" % event)
                self._queue.task_done()
                eventlet.sleep(0.3)

    def pack_message(self, message):
        data = None
        try:
            data = msgpack.packb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return data

    def _send_event_ex(self, entry):
        pub_socket = Socket(PUB)
        pub_socket.bind(
                "tcp://" + self.ip + ":" + self.controllers_updates_port)
        pub_socket.send(self.pack_message('sync'))
        eventlet.sleep(0.5)
        pub_socket.send(self.pack_message(entry))
        eventlet.sleep(0.5)
        pub_socket.close()

    def send_event(self, table, key, action, value):
        entry = table + "@" + key + "@" + action + "@" + value
        if self.is_daemonize:
            self._queue.put(entry)
            eventlet.sleep(0.2)
        else:
            self._send_event_ex(entry)


def main():
    pubsub = PublisherAgent('127.0.0.1', None, None)
    pubsub._send_event_ex("ping")
    pubsub.daemonize()
    while True:
        pubsub.send_event("t", "k", "a", "v")


if __name__ == "__main__":
    main()
