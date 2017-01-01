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

from oslo_config import cfg


from dragonflow.common import periodic_tasks


def run_status_reporter(status_update_callback, nb_api, host, binary):
    def heartbeat_reporter():
        while True:
            yield(host, binary)

    periodic_reporter = periodic_tasks.PeriodicTasks(
        status_update_callback,
        heartbeat_reporter,
        cfg.CONF.df.report_interval)

    periodic_reporter.daemonize()
