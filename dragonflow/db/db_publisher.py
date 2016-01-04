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


eventlet.monkey_patch(all=True)


class PublisherAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_pub=False):
        super(PublisherAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        #TODO(gampel) move to configuration
        self.port = "8861"

        self.pub_socket = None
        self._queue = eventlet.queue.PriorityQueue()
        self.is_daemonize = False

    def daemonize(self):
        self.is_daemonize = True
        eventlet.spawn(self.run)
        self._queue.put('sync')
        eventlet.sleep(0)

    def run(self):
        self.pub_socket = Socket(PUB)
        self.endpoint = self.pub_socket.bind("tcp://*:" + self.port)
        self.pub_socket.send('sync')
        while True:
            event = None
            eventlet.sleep(0)
            try:
                event = self._queue.get(timeout=60)
            except eventlet.queue.Empty:
                self.pub_socket.send("sync")
                eventlet.sleep(1)
            else:
                data = msgpack.packb(event)
                self.pub_socket.send(data)
                self._queue.task_done()
                eventlet.sleep(0.2)

    def _send_event_ex(self, entry):
        self.pub_socket = Socket(PUB)
        #TODO(gampel) when the compute and server are on the same machine
        #this will not work as the port is allready bound
        self.pub_socket.bind("tcp://*:" + self.port)
        eventlet.sleep(0)
        self.pub_socket.send(entry)
        eventlet.sleep(1)
        self.pub_socket.close()

    def send_event(self, table, key, action, value):
        entry = table + "@" + key + "@" + action + "@" + value
        if self.is_daemonize:
            self._queue.put(entry)
            eventlet.sleep(0)
        else:
            self._send_event_ex(entry)


def main():
    pubsub = PublisherAgent('127.0.0.1', None, None)
    pubsub.daemonize()
    while True:
        pubsub.send_event("t", "k", "a", "v")


if __name__ == "__main__":
    main()
