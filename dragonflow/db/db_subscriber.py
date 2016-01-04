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


from oslo_log import log as logging

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
        self.plugin_updates_port = "8861"
        self.controllers_updates_port = "8862"
        self.pool = eventlet.GreenPool()

    def _connect(self, port):
        sub_socket = Socket(SUB)
        sub_socket.set_string_option(SUB, SUB_SUBSCRIBE, "")
        sub_socket.connect("tcp://" + self.ip + ":" + port)
        return sub_socket

    def unpack_message(self, message):
        entry = None
        try:
            entry = msgpack.unpackb(message, encoding='utf-8')
        except Exception as e:
            LOG.warn(e)
        return entry

    def run(self, name, port):
        sub_socket = self._connect(port)
        LOG.info(_LI("Starting  %(name)s Subscriber on port %(port_no)s")
                % {'port_no': port, 'name': name})
        while True:
            try:
                eventlet.sleep(0.1)
                data = sub_socket.recv()
                entry = self.unpack_message(data)
                if not entry:
                    continue
                if entry == 'sync':
                    continue
                entries = entry.split('@')
                # entries = [table, key, action, value]
                self.db_changes_callback(entries[0], entries[1], entries[2],
                                         entries[3])
            except Exception as e:
                LOG.warn(e)
                sub_socket.close()
                del sub_socket
                sub_socket = self._connect(port)
                LOG.debug(sub_socket)

    def daemonize(self):
        self.pool.spawn_n(self.run, "Plugin", self.plugin_updates_port)
        eventlet.sleep(0)
        self.pool.spawn_n(
                self.run,
                "Controllers",
                self.controllers_updates_port)
