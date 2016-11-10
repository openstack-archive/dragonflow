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

import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.common import constants
from dragonflow.db import db_common
from dragonflow.db import port_status_api
from dragonflow.db import pub_sub_api


LOG = log.getLogger(__name__)


class RedisPortStatusNotifier(port_status_api.PortStatusDriver):
    # PortStatusNotifier implements port status update
    # southbound notification mechanism based on redis
    # pub/sub driver at present.

    def __init__(self):
        self.mech_driver = None
        self.nb_api = None
        self.db_table_monitor = None
        self.pub = None
        self.sub = None

    def initialize(self, mech_driver, nb_api, pub, sub,
                   is_neutron_server=False):
        self.mech_driver = mech_driver
        self.nb_api = nb_api
        self.pub = pub
        self.sub = sub

        if is_neutron_server:
            # for pub/sub use case,code in server node,
            # keeping topic alive default in use.
            self.start_subscriber()
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
        self.db_table_monitor = self._start_db_table_monitor('pubsub')

    def notify_port_status(self, ovs_port, status):
        port_id = ovs_port.get_iface_id()
        self._send_port_status_event('lport', port_id, 'update', status)

    # server code
    def _start_db_table_monitor(self, table_name):
        table_monitor = PortStatusMonitor(
            table_name,
            self.nb_api.driver,
            self.pub,
            cfg.CONF.df.publisher_timeout,
            cfg.CONF.df.monitor_table_poll_time,
            cfg.CONF.df.local_ip
        )
        table_monitor.daemonize()
        return table_monitor

    def _stop_db_table_monitor(self):
        if not self.db_table_monitor:
            return
        self.db_table_monitor.stop()
        self.db_table_monitor = None

    # server code
    def port_status_callback(self, table, key, action, value, topic=None):
        if 'lport' == table and 'update' == action:
            LOG.info(_LI("Process port %s status update event"), str(key))
            if constants.PORT_STATUS_UP == value:
                self.mech_driver.set_port_status_up(key)
            if constants.PORT_STATUS_DOWN == value:
                self.mech_driver.set_port_status_down(key)

    # local controller code
    def _send_port_status_event(self, table, key, action, value):
        topic = self.nb_api.get_all_port_status_keys()
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        self.pub.send_event(update)

    # server code
    def start_subscriber(self):
        self.sub.initialize(self.port_status_callback)
        server_ip = cfg.CONF.df.local_ip
        self.sub.register_topic(server_ip)
        # In portstats table, there are key value pairs like this:
        # port_status_192.168.1.10 : 192.168.1.10
        self.nb_api.create_port_status(server_ip)
        self.sub.daemonize()

    def start_publisher(self):
        self.pub.initialize()


class PortStatusMonitor(pub_sub_api.TableMonitor):
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
        self._driver.set_key(self.table_name, self._server_ip,
                             time.time(), None)
