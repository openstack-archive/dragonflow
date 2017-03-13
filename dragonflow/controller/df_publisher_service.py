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
from eventlet import queue
import sys
import traceback

from neutron.agent.common import config
from neutron.common import config as common_config
from oslo_log import log as logging

from dragonflow._i18n import _LW
from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.db import db_common
from dragonflow.db import pub_sub_api


LOG = logging.getLogger(__name__)


class PublisherService(object):
    def __init__(self):
        self._queue = queue.Queue()
        self.publisher = self._get_publisher()
        self.multiproc_subscriber = self._get_multiproc_subscriber()
        self.db = df_utils.load_driver(
            cfg.CONF.df.nb_db_class,
            df_utils.DF_NB_DB_DRIVER_NAMESPACE)

    def _get_publisher(self):
        pub_sub_driver = df_utils.load_driver(
                                    cfg.CONF.df.pub_sub_driver,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_publisher()

    def _get_multiproc_subscriber(self):
        """
        Return the subscriber for inter-process communication. If multi-proc
        communication is not use (i.e. disabled from config), return None.
        """
        if not cfg.CONF.df.pub_sub_use_multiproc:
            return None
        pub_sub_driver = df_utils.load_driver(
                                    cfg.CONF.df.pub_sub_multiproc_driver,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_subscriber()

    def initialize(self):
        if self.multiproc_subscriber:
            self.multiproc_subscriber.initialize(self._append_event_to_queue)
        self.publisher.set_publisher_role(constants.ROLE_NEUTRON_SERVER)
        self.publisher.initialize()

    def _append_event_to_queue(self, table, key, action, value, topic):
        event = db_common.DbUpdate(table, key, action, value, topic=topic)
        self._queue.put(event)
        eventlet.sleep(0)

    def run(self):
        if self.multiproc_subscriber:
            self.multiproc_subscriber.daemonize()
        self.db.initialize(
            db_ip=cfg.CONF.df.remote_db_ip,
            db_port=cfg.CONF.df.remote_db_port,
            config=cfg.CONF.df
        )
        self._start_db_table_monitors()
        while True:
            try:
                event = self._queue.get()
                self.publisher.send_event(event)
                eventlet.sleep(0)
            except Exception as e:
                LOG.warning(_LW("Exception in main loop: {}, {}").format(
                    e, traceback.format_exc()
                ))
                # Ignore

    def _start_db_table_monitor(self, table_name):
        if table_name == 'publisher':
            table_monitor = pub_sub_api.StalePublisherMonitor(
                self.db,
                self.publisher,
                cfg.CONF.df.publisher_timeout,
                cfg.CONF.df.monitor_table_poll_time,
            )
        else:
            table_monitor = pub_sub_api.TableMonitor(
                table_name,
                self.db,
                self.publisher,
                cfg.CONF.df.monitor_table_poll_time,
            )
        table_monitor.daemonize()
        return table_monitor

    def _start_db_table_monitors(self):
        self.db_table_monitors = [self._start_db_table_monitor(table_name)
                                  for table_name in pub_sub_api.MONITOR_TABLES]


def main():
    common_config.init(sys.argv[1:])
    config.setup_logging()
    service = PublisherService()
    service.initialize()
    service.run()
