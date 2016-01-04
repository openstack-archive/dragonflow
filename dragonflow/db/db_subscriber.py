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
import zmq

from oslo_log import log as logging
from oslo_serialization import jsonutils

from neutron.i18n import _LI

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


class SubscriberAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_pub=False):
        super(SubscriberAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        #TODO(gampel) move to configuration
        self.plugin_updates_port = "8866"
        self.controllers_updates_port = "8867"
        self.pool = eventlet.GreenPool()

    def _connect(self, port):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect(
                "tcp://" + self.ip + ":" + self.plugin_updates_port)
        socket.connect(
                "tcp://" + self.ip + ":" + self.controllers_updates_port)
        socket.setsockopt(zmq.SUBSCRIBE, b"D")
        return socket

    def unpack_message(self, message):
        entry = None
        try:
            entry = msgpack.unpackb(message, encoding='utf-8')
        except Exception as e:
            LOG.warning(e)
        return entry

    def run(self, name, port):
        sub_socket = self._connect(port)
        LOG.info(_LI("Starting  %(name)s Subscriber on port %(port_no)s")
                % {'port_no': port, 'name': name})
        while True:
            try:
                eventlet.sleep(0.1)
                [topic, data] = sub_socket.recv_multipart()
                entry_json = self.unpack_message(data)
                entries = jsonutils.loads(entry_json)
                # entries = [table, key, action, value]
                self.db_changes_callback(entries[0], entries[1], entries[2],
                                         entries[3])
            except Exception as e:
                LOG.warning(e)
                sub_socket.close()
                del sub_socket
                sub_socket = self._connect(port)
                LOG.debug(sub_socket)

    def daemonize(self):
        self.pool.spawn_n(self.run, "Plugin", self.plugin_updates_port)
        eventlet.sleep(0)


def main():
    pubsub = SubscriberAgent('127.0.0.1', None, db_change_callback_test)
    pubsub.run("ttt", 8866)


def db_change_callback_test(table, key, action, value):
    print key


if __name__ == "__main__":
    main()
