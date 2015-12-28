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
from nanomsg import Socket, SUB, PUB, SUB_SUBSCRIBE

eventlet.monkey_patch()

class PubSubAgent(object):

    def __init__(self, ip, db_driver, db_changes_callback, is_pub=False):
        super(PubSubAgent, self).__init__()
        self.db_driver = db_driver
        self.db_changes_callback = db_changes_callback
        self.ip = ip
        self.sub_socket = None
        self.pub_socket = None
        if is_pub:
            self.pub_socket = Socket(PUB)
            self.pub_socket.bind("tcp://" + self.ip + ":5560")
            self.pub_socket.send('sync')
        self.pool = eventlet.GreenPool(size=1)

    def send_event(self, table, key, action, value):
        entry = table + "@" + key + "@" + action + "@" + value
        print "Sending entry"
        print entry
        self.pub_socket.send(entry)

    def run(self):
        print ' in Run'
        self.sub_socket = Socket(SUB)
        self.sub_socket.set_string_option(SUB, SUB_SUBSCRIBE, "")
        self.sub_socket.connect("tcp://" + self.ip + ":5560")
        print self.sub_socket
        while True:
            try:
                entry = self.sub_socket.recv()
                if entry == 'sync':
                    continue
                entries = entry.split('@')
                # entries = [table, key, action, value]
                print entries
                self.db_changes_callback(entries[0], entries[1], entries[2],
                                         entries[3])
            except Exception:
                self.sub_socket.close()
                self.sub_socket.connect("tcp://" + self.ip + ":5560")

    def daemonize(self):
        print 'Daemonize'
        self.pool.spawn_n(self.run)


def main():
    pubsub = PubSubAgent('127.0.0.1', None, None)
    pubsub.run()


if __name__ == "__main__":
    main()
