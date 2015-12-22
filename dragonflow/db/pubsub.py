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

import serf


class PubSubAgent(object):

    def __init__(self, db_driver, ip):
        super(PubSubAgent, self).__init__()
        self.db_driver = db_driver
        self.client = serf.Client(ip + ':7373')
        self.client.connect()

    def _callback(self, response):
        print response.body['Name']
        print response.body['Payload']

    def run(self):
        while True:
            try:
                self.client.stream(Type='*',).add_callback(
                    self._callback, ).watch()
            except Exception:
                pass

    def send_event(self):
        self.client.event(
            Name='event_i_am_alive-%s' % 4,
            Payload='test',
            Coalesce=False).request()


def main():
    pubsub = PubSubAgent(None, '127.0.0.1')
    pubsub.run()
    #pubsub.send_event()
    pubsub.client.disconnect()


if __name__ == "__main__":
    main()
