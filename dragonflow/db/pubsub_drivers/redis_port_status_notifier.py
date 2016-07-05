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

import eventlet
import random
import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.db.db_common import DbUpdate
from dragonflow.db.port_status import Portstatus
from dragonflow.db.pub_sub_api import TableMonitor


LOG = log.getLogger(__name__)


class PortStatusNotifier(Portstatus):
    # PortStatusNotifier implements port status update
    # southbound notification mechanism based on redis
    # pub/sub driver at present.

    def __init__(self):
        self.mech_driver = None
        self.is_neutron_server = False
        self.nb_api = None
        self.status_callback = None
        self.db_table_monitors = None

    def initialise(self, mech_driver, nb_api, is_neutron_server=False):
        self.mech_driver = mech_driver
        self.is_neutron_server = is_neutron_server
        self.nb_api = nb_api
        if self.is_neutron_server:
            # for pub/sub use case,code in server node,
            # keeping topic alive default in use.
            self.start_subsciber()
            self.server_status_monitors()
        else:
            # for pub/sub design, local controller will send
            # pub/sub event to notify server if there is a
            # new port status update
            self.start_publisher()

    def server_status_monitors(self):
        # In pub/sub design, we need to mark a new timestamp
        # periodically, so consistency tool will check if a
        # server is alive.
        self.db_table_monitors = self._start_db_table_monitor('pubsub')

    def notify_port_status(self, ovs_port, status):
        port_id = ovs_port.get_iface_id()
        self._send_port_status_event('lport', port_id, 'update', status)

    # sever code
    def _start_db_table_monitor(self, table_name):
        table_monitor = PortStatusMonitor(
            table_name,
            self.nb_api.driver,
            self.nb_api.publisher,
            cfg.CONF.df.publisher_timeout,
            cfg.CONF.df.monitor_table_poll_time,
            cfg.CONF.df.local_ip
        )
        table_monitor.daemonize()
        return table_monitor

    def _stop_db_table_monitors(self):
        if not self.db_table_monitors:
            return
        for monitor in self.db_table_monitors:
            monitor.stop()
        self.db_table_monitors = None

    # server code
    def port_status_callback(self, table, key, action, value, topic=None):
        if 'lport' == table and 'update' == action:
            LOG.info(_LI("Port status update"))
            if 'up' == value:
                self.mech_driver.set_port_status_up(key)
            if 'down' == value:
                self.mech_driver.set_port_status_down(key)
            eventlet.sleep(0)

    # local controller code
    def _send_port_status_event(self, table, key, action, value):
        topics = self.nb_api.driver.get_all_entries('portstats')
        topic = random.choice(topics)
        update = DbUpdate(table, key, action, value, topic=topic)
        self.nb_api.publisher.send_event(update)
        eventlet.sleep(0)

    # server  code
    def start_subsciber(self):
        self.nb_api.subscriber.initialize(self.port_status_callback)
        server_ip = cfg.CONF.df.local_ip
        self.nb_api.subscriber.register_topic(server_ip)
        # In portstats table, there are key value pairs like this:
        # port_status_192.168.1.10 : 192.168.1.10
        self.nb_api.driver.create_key('portstats', server_ip,
                                      server_ip, None)
        self.nb_api.subscriber.daemonize()

    def start_publisher(self):
        self.nb_api.publisher.initialize()


class PortStatusMonitor(TableMonitor):
    def __init__(self, table_name, driver, publisher=None,
                 timeout=1, polling_time=10, local_ip='127.0.0.1'):
        super(PortStatusMonitor, self).__init__(
            table_name,
            driver,
            publisher,
            polling_time
        )
        self._timeout = timeout
        self._server_ip = local_ip
        self.table_name = table_name
        # In table pubsub, there are key values pairs like this
        # port_status_192.168.1.10 : timestamp
        self._driver.create_key(self.table_name, self._server_ip,
                                time.time(), None)

    def _poll_once(self, old_cache):
        # update server port status timestamp in DB, leave
        # timeout process to DB sync tool
        self._driver.create_key(self.table_name, self._server_ip,
                                time.time(), None)
