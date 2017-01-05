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

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.common import constants
from dragonflow.db import db_common
from dragonflow.db import models
from dragonflow.db import port_status_api


LOG = log.getLogger(__name__)


class RedisPortStatusNotifier(port_status_api.PortStatusDriver):
    # PortStatusNotifier implements port status update
    # southbound notification mechanism based on redis
    # pub/sub driver at present.

    def __init__(self):
        self.mech_driver = None
        self.nb_api = None
        self.pub = None
        self.sub = None

    def initialize(self, mech_driver, nb_api, pub, sub,
                   is_neutron_server=False):
        self.mech_driver = mech_driver
        self.nb_api = nb_api
        self.pub = pub
        self.sub = sub

        if is_neutron_server:
            self.start_subscriber()
        else:
            # for pub/sub design, local controller will send
            # pub/sub event to notify server if there is a
            # new port status update
            self.start_publisher()

    def notify_port_status(self, ovs_port, status):
        port_id = ovs_port.get_iface_id()
        self._send_port_status_event(models.LogicalPort.table_name,
                                     port_id, 'update', status)

    # server code
    def port_status_callback(self, table, key, action, value, topic=None):
        if models.LogicalPort.table_name == table and 'update' == action:
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
        server_ip = cfg.CONF.df.management_ip
        self.sub.register_topic(server_ip)
        # In portstats table, there are key value pairs like this:
        # port_status_192.168.1.10 : 192.168.1.10
        self.nb_api.create_port_status(server_ip)
        self.sub.daemonize()

    def start_publisher(self):
        self.pub.initialize()
