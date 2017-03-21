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

from dragonflow._i18n import _LE, _LW
from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import models
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db import port_status_api

LOG = log.getLogger(__name__)


class RedisPortStatusNotifier(port_status_api.PortStatusDriver):
    # PortStatusNotifier implements port status update
    # southbound notification mechanism based on redis
    # pub/sub driver at present.
    def __init__(self):
        self.nb_api = None

    def initialize(self, nb_api, is_neutron_server=False):
        self.nb_api = nb_api
        if is_neutron_server:
            self.create_heart_beat_reporter(cfg.CONF.host)
        else:
            if not cfg.CONF.df.enable_df_pub_sub:
                LOG.warning(_LW("RedisPortStatusNotifier cannot "
                                "work when enable_df_pub_sub is disabled"))
                return
            self.nb_api.publisher.initialize()

    @lock_db.wrap_db_lock(lock_db.RESOURCE_NEUTRON_LISTENER)
    def create_heart_beat_reporter(self, host):
        listener = self.nb_api.get_neutron_listener(host)
        if not listener:
            self._create_heart_beat_reporter(host)
        else:
            ppid = listener.get_ppid()
            my_ppid = os.getppid()
            LOG.info("Listener %(l)s exists, my ppid is %(ppid)s",
                     {'l': listener, 'ppid': my_ppid})
            # FIXME(wangjian): if api_worker is 1, the old ppid could be
            # equal to my_ppid. I tried to set api_worker=1, still multiple
            # neutron-server processes were created.
            if ppid != my_ppid:
                self.nb_api.delete_neutron_listener(host)
                self._create_heart_beat_reporter(host)

    def _create_heart_beat_reporter(self, host):
        self.nb_api.register_listener_callback(self.port_status_callback,
                                               'listener_' + host)
        LOG.info("Register listener %s", host)
        self.heart_beat_reporter = HeartBeatReporter(self.nb_api)
        self.heart_beat_reporter.daemonize()

    def notify_port_status(self, ovs_port, status):
        port_id = ovs_port.get_iface_id()
        self._send_event(models.LogicalPort.table_name,
                         port_id, 'update', status)

    def _send_event(self, table, key, action, value):
        listeners = self.nb_api.get_all_neutron_listeners()
        listeners_num = len(listeners)
        if listeners_num > 1:
            # Sort by timestamp and choose from the latest ones randomly.
            # 1. This can avoid we always choose the same listener in one
            # single interval
            # 2. Compare to choose from whose timestamp is within a threshold,
            # e.g 2 * neutron_listener_report_interval,
            # this way is the easier and can reduce the possibility a dead
            # one is chosen. For users, do not need to figure out what is
            # the best report interval. A big interval increase the possility a
            # dead one is chosen, while a small one may affect the performance
            listeners.sort(key=lambda l: l.get_timestamp(), reverse=True)
            selected = random.choice(listeners[:len(listeners) / 2])
        elif listeners_num == 1:
            selected = listeners[0]
        else:
            LOG.warning(_LW("No neutron listener found"))
            return
        topic = selected.get_topic()
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        LOG.info("Publish to neutron %s", topic)
        self.nb_api.publisher.send_event(update)

    def port_status_callback(self, table, key, action, value, topic=None):
        if models.LogicalPort.table_name == table and 'update' == action:
            LOG.info("Process port %s status update event", str(key))
            if constants.PORT_STATUS_UP == value:
                self.mech_driver.set_port_status_up(key)
            if constants.PORT_STATUS_DOWN == value:
                self.mech_driver.set_port_status_down(key)


class HeartBeatReporter(object):
    """Updates heartbeat timestamp periodically with a random delay."""

    def __init__(self, api_nb):
        self.api_nb = api_nb
        self._daemon = df_utils.DFDaemon()

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def run(self):
        listener = cfg.CONF.host
        ppid = os.getppid()
        self.api_nb.create_neutron_listener(listener,
                                            timestamp=int(time.time()),
                                            ppid=ppid)

        cfg_interval = cfg.CONF.df.neutron_listener_report_interval
        delay = cfg.CONF.df.neutron_listener_report_delay

        while True:
            try:
                # We delay a random time to avoid a periodical peak of network
                # throughput and pressure for df-db in a big scale
                interval = random.randint(cfg_interval, cfg_interval + delay)
                time.sleep(interval)
                timestamp = int(time.time())
                self.api_nb.update_neutron_listener(listener,
                                                    timestamp=timestamp,
                                                    ppid=ppid)
            except Exception:
                LOG.exception(_LE(
                        "Failed to report heart beat for %s"), listener)
