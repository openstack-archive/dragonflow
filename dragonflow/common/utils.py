# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from oslo_log import log as logging

import eventlet

from dragonflow._i18n import _LE

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


class DFDaemon(object):

    def __init__(self):
        super(DFDaemon, self).__init__()
        self.pool = eventlet.GreenPool()
        self.is_daemonize = False
        self.thread = None

    def daemonize(self, run):
        if self.is_daemonize:
            LOG.error(_LE("already daemonized"))
            return
        self.thread = self.pool.spawn_n(run)
        eventlet.sleep(0)
        self.is_daemonize = True
        return self.thread

    def stop(self):
        if self.is_daemonize and self.thread:
            eventlet.greenthread.kill(self.thread)
            eventlet.sleep(0)
            self.thread = None
            self.is_daemonize = False
