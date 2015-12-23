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
import serf


class PubSubAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback):
        super(PubSubAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.client = serf.Client(ip + ':7373')
        self.client.connect()
        self.pool = eventlet.GreenPool(size=1)

    def send_event(self, table, key, action):
        entry = action + ":" + key
        self.client.event(
            Name=table,
            Payload=entry,
            Coalesce=False).request()

    def _callback(self, response):
        table = response.body['Name']
        entry = response.body['Payload']
        fields = entry.split(':')
        action = fields[0]
        key = fields[1]
        if action == 'delete':
            self.db_changes_callback(table, key,
                                     'delete', None)
            return

        value = self.db_driver.get_key(table, key)
        self.db_changes_callback(table, key, action, value)

    def run(self):
        while True:
            try:
                self.client.stream(Type='*',).add_callback(
                    self._callback, ).watch()
            except Exception:
                pass

    def daemonize(self):
        self.pool.spawn_n(self.run)


def main():
    pubsub = PubSubAgent(None, '127.0.0.1')
    pubsub.run()
    #pubsub.send_event()
    pubsub.client.disconnect()


if __name__ == "__main__":
    main()
