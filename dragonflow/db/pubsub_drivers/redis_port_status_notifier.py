# Copyright (c) 2015 OpenStack Foundation.
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

import os
import random
import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LE, _LI, _LW
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import port_status_api
from dragonflow.db.neutron import lockedobjects_db as lock_db

LOG = log.getLogger(__name__)


class RedisPortStatusNotifier(port_status_api.PortStatusDriver):
    """
        This class is used to implement southbound notification
        mechanism based on pub/sub mechanism
    """
    def __init__(self):
        self.nb_api = None

    def initialize(self, nb_api, is_neutron_server=False):
        self.nb_api = nb_api
        if is_neutron_server:
            self.create_heart_beat_reporter(cfg.CONF.host)
        else:
            if not cfg.CONF.df.use_pubsub:
                LOG.warning(_LW("RedisPortStatusNotifier can not "
                                "work when use_pubsub is disabled"))
                return
            self.nb_api.publisher.initialize()

    @lock_db.wrap_db_lock(lock_db.RESOURCE_NEUTRON_LISTENER)
    def create_heart_beat_reporter(self, host):
        listener = self.nb_api.get_neutron_listener(host)
        if listener is None:
            self._create_heart_beat_reporter(self, host)
        else:
            ppid = listener.get_ppid()
            my_ppid = os.getppid()
            LOG.info(_LI("Listener %(l)s exists, my ppid is %(ppid)s"),
                     {'l': listener, 'ppid': my_ppid})
            # FIXME(wangjian): if api_worker is 1, the old ppid could is
            # equal to my_ppid. I tried to set api_worker=1, still multiple
            # neutron-server processes were created.
            if ppid != my_ppid:
                self._create_heart_beat_reporter(host)

    def _create_heart_beat_reporter(self, host):
        self.nb_api.register_listener_callback(self._nb_callback,
                                               'n_listener_' + host)
        LOG.info(_LI("Register listener %s"), host)
        self.heart_beat_reporter = HearBeatReporter(self.nb_api)
        self.heart_beat_reporter.daemonize()

    def notify_port_status(self, ovs_port, status):
        port_id = ovs_port.get_iface_id()
        self._send_event('lport', port_id, 'update', status)

    def _send_event(self, table, key, action, value):
        listeners = self.nb_api.get_all_neutron_listeners()
        l = len(listeners)
        if l == 0:
            LOG.warning(_LW("No neutron listener found"))
            return
        elif l == 1:
            n = listeners[0]
        else:
            # sort by timestamp and choose from the latest ones. This can
            # avoid a dead one is chosen as far as possible
            listeners.sort(key=lambda l: l.get_timestamp(), reverse=True)
            n = random.choice(listeners[:len(listeners) / 2])
        t = n.get_topic()
        update = db_common.DbUpdate(table, key, action, value, topic=t)
        LOG.info(_LI("Publish to neutron %s"), t)
        self.nb_api.publisher.send_event(update)

class HearBeatReporter(object):
    def __init__(self, api_nb):
        self.api_nb = api_nb
        self._daemon = df_utils.DFDaemon()

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def run(self):
        listener = cfg.CONF._host
        ppid = os.getppid()
        self.api_nb.create_neutron_listener(listener,
                                            timestamp=int(time.time()),
                                            ppid=ppid)

        cfg_interval = cfg.CONF.df.neutron_listener_report_interval
        delay = cfg.CONF.df.neutron_listener_report_delay

        while True:
            try:
                interval = random.randint(cfg_interval, cfg_interval + delay)
                time.sleep(interval)
                timestamp = int(time.time())
                self.api_nb.update_neutron_listener(listener,
                                                    timestamp=timestamp,
                                                    ppid=ppid)
            except Exception:
                LOG.exception(_LE(
                        "Failed to report heart beat for %s"), listener)
