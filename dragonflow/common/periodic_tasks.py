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

import logging
import time


from dragonflow._i18n import _LE
from dragonflow.common import utils as df_utils

LOG = logging.getLogger(__name__)


class PeriodicTasks(object):
    def __init__(self, callback, args_generator, interval):
        self.callback = callback
        self.args_generator = args_generator
        self.interval = interval
        self._daemon = df_utils.DFDaemon()

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def run(self):
        args = self.args_generator()
        while True:
            try:
                time.sleep(self.interval)
                self.callback(*next(args))
            except Exception:
                # FIXME(Rajiv): Log the periodic task identity to make
                # debugging easier.
                LOG.exception(_LE("Failed to perform periodic task for ****"))
