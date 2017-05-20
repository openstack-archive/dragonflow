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

import functools

from oslo_log import log
from oslo_service import loopingcall

from dragonflow import conf as cfg
from dragonflow.db.models import service


LOG = log.getLogger(__name__)


service_names = {}


def run_status_reporter(callback):
    def report_status():
        try:
            callback()
        except Exception:
            LOG.exception("Failed to report status")
        return True

    timer = loopingcall.FixedIntervalLoopingCall(report_status)
    timer.start(interval=cfg.CONF.df.report_interval)


def register_service(service_name, nb_api, instance=None):
    if instance:
        service_names[id(instance)] = service_name
    chassis_id = cfg.CONF.host
    nb_api.create(service.Service(chassis=chassis_id, binary=service_name),
                  skip_send_event=True)
    callback = functools.partial(service.Service.update_last_seen,
                                 nb_api, chassis_id, service_name)
    run_status_reporter(callback)
