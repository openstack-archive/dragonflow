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

from neutron_lib import context as n_context
from neutron_lib.plugins import directory
from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall

from dragonflow.db import db_common
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db import neutron_notifier_api

LOG = log.getLogger(__name__)


class NbApiNeutronNotifier(neutron_notifier_api.NeutronNotifierDriver):
    # NbApiNeutronNotifier implements notification mechanism from
    # Dragonflow controller to northbound neutron server, based on
    # pub/sub driver at present.
    def __init__(self):
        self.nb_api = None

    def initialize(self, nb_api, is_neutron_server=False):
        self.nb_api = nb_api
        if is_neutron_server:
            self.create_heart_beat_reporter(cfg.CONF.host)
        else:
            if not cfg.CONF.df.enable_df_pub_sub:
                LOG.warning("NbApiNeutronNotifier cannot "
                            "work when enable_df_pub_sub is disabled")
                return
            self.nb_api.publisher.initialize()

    @lock_db.wrap_db_lock(lock_db.RESOURCE_NEUTRON_LISTENER)
    def create_heart_beat_reporter(self, host):
        listener = self.nb_api.get(core.Listener(id=host))
        if listener is None:
            self._create_heart_beat_reporter(host)
        else:
            ppid = listener.ppid
            my_ppid = os.getppid()
            LOG.info("Listener %(l)s exists, my ppid is %(ppid)s",
                     {'l': listener, 'ppid': my_ppid})
            # FIXME(wangjian): if api_worker is 1, the old ppid could be
            # equal to my_ppid. I tried to set api_worker=1, still multiple
            # neutron-server processes were created.
            if ppid != my_ppid:
                self.nb_api.delete(listener)
                self._create_heart_beat_reporter(host)

    def _create_heart_beat_reporter(self, host):
        listener = core.Listener(
            id=host,
            ppid=os.getppid(),
        )
        self.nb_api.register_listener_callback(self.notify_neutron_server,
                                               listener.topic)
        LOG.info("Register listener %s", listener.id)
        self.heart_beat_reporter = HeartBeatReporter(self.nb_api, listener)
        self.heart_beat_reporter.daemonize()

    def notify_port_status(self, ovs_port, status):
        port = ovs_port.lport
        self._send_event(l2.LogicalPort.table_name, port.id, 'update', status)

    def _send_event(self, table, key, action, value):
        listeners = self.nb_api.get_all(core.Listener)
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
            listeners.sort(key=lambda l: l.timestamp, reverse=True)
            selected = random.choice(listeners[:len(listeners) / 2])
        elif listeners_num == 1:
            selected = listeners[0]
        else:
            LOG.warning("No neutron listener found")
            return
        topic = selected.topic
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        LOG.info("Publish to neutron %s", topic)
        self.nb_api.publisher.send_event(update)

    def notify_neutron_server(self, table, key, action, value, topic=None):
        if l2.LogicalPort.table_name == table and 'update' == action:
            LOG.info("Process port %s status update event", key)
            core_plugin = directory.get_plugin()
            core_plugin.update_port_status(n_context.get_admin_context(),
                                           key, value)


class HeartBeatReporter(object):
    """Updates heartbeat timestamp periodically with a random delay."""

    def __init__(self, api_nb, listener):
        self.api_nb = api_nb
        self.listener = listener
        # We delay a random time to avoid a periodical peak of network
        # throughput and pressure for df-db in a big scale
        self._loopingcall = loopingcall.DynamicLoopingCall(self.run)

    def get_delay(self):
        cfg_interval = cfg.CONF.df.neutron_listener_report_interval
        delay = cfg.CONF.df.neutron_listener_report_delay
        return random.randint(cfg_interval, cfg_interval + delay)

    def daemonize(self):
        self.api_nb.create(self.listener)
        self._loopingcall.start(self.get_delay())

    def stop(self):
        return self._loopingcall.stop()

    def run(self):
        self.api_nb.update(self.listener)
        return self.get_delay()
