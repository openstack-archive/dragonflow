#
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
from nanomsg import Socket, SUB, SUB_SUBSCRIBE

eventlet.monkey_patch()


class SubscriberAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_pub=False):
        super(SubscriberAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        #TODO(gampel) move to configuration
        self.port = "8861"
        self.sub_socket = None
        self.pool = eventlet.GreenPool(size=1)

    def _connect(self):
        self.sub_socket = Socket(SUB)
        self.sub_socket.set_string_option(SUB, SUB_SUBSCRIBE, "")
        self.endpoint = self.sub_socket.connect(
                "tcp://" + self.ip + ":" + self.port)

    def run(self):
        self._connect()
        while True:
            try:
                eventlet.sleep(0)
                data = self.sub_socket.recv()
                entry = msgpack.unpackb(data, encoding='utf-8')
                if entry == 'sync':
                    continue
                entries = entry.split('@')
                # entries = [table, key, action, value]
                self.db_changes_callback(entries[0], entries[1], entries[2],
                                         entries[3])
            except Exception:
                #self.endpoint.shutdown()
                self.sub_socket.close()
                self._connect()

    def daemonize(self):
        self.pool.spawn_n(self.run)
