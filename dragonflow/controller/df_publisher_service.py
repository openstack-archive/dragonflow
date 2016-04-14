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
from Queue import Queue
import sys
import time
import traceback

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils

from neutron.agent.common import config
from neutron.common import config as common_config

from dragonflow._i18n import _LW
from dragonflow.common import common_params
from dragonflow.common import exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import pub_sub_api

eventlet.monkey_patch()

LOG = logging.getLogger(__name__)


class PublisherService(object):
    def __init__(self):
        self._queue = Queue()
        self.publisher = self._get_publisher()
        self.multiproc_subscriber = self._get_multiproc_subscriber()
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.db = nb_driver_class()
        self.uuid = pub_sub_api.generate_publisher_uuid()
        self._rate_limit = df_utils.RateLimiter(
            cfg.CONF.df.publisher_rate_limit_count,
            cfg.CONF.df.publisher_rate_limit_timeout,
        )

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
        self.publisher.initialize()
        # TODO(oanson) TableMonitor initialisation goes here

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
        self._register_as_publisher()
        self._publishers_table_monitor = pub_sub_api.StalePublisherMonitor(
            self.db,
            self.publisher,
            cfg.CONF.df.publisher_timeout
        )
        self._publishers_table_monitor.daemonize()
        # TODO(oanson) TableMonitor daemonize will go here
        while True:
            try:
                event = self._queue.get()
                self.publisher.send_event(event)
                if event.table != pub_sub_api.PUBLISHER_TABLE:
                    self._update_timestamp_in_db()
                eventlet.sleep(0)
            except Exception as e:
                LOG.warning(_LW("Exception in main loop: {}, {}").format(
                    e, traceback.format_exc()
                ))
                # Ignore

    def _update_timestamp_in_db(self):
        if self._rate_limit():
            return
        try:
            publisher_json = self.db.get_key(
                pub_sub_api.PUBLISHER_TABLE,
                self.uuid,
            )
            publisher = jsonutils.loads(publisher_json)
            publisher['last_activity_timestamp'] = time.time()
            publisher_json = jsonutils.dumps(publisher)
            self.db.set_key(
                pub_sub_api.PUBLISHER_TABLE,
                self.uuid,
                publisher_json
            )
        except exceptions.DBKeyNotFound:
            self._register_as_publisher()

    def _register_as_publisher(self):
        publisher = {
            'id': self.uuid,
            'uri': self._get_uri(),
            'last_activity_timestamp': time.time(),
        }
        publisher_json = jsonutils.dumps(publisher)
        self.db.create_key(
            pub_sub_api.PUBLISHER_TABLE,
            self.uuid, publisher_json
        )

    def _get_uri(self):
        ip = cfg.CONF.df.publisher_bind_address
        if ip == '*' or ip == '127.0.0.1':
            ip = cfg.CONF.df.local_ip
        return "{}://{}:{}".format(
            cfg.CONF.df.publisher_transport,
            ip,
            cfg.CONF.df.publisher_port,
        )


def main():
    cfg.CONF.register_opts(common_params.df_opts, 'df')
    common_config.init(sys.argv[1:])
    config.setup_logging()
    service = PublisherService()
    service.initialize()
    service.run()

if __name__ == "__main__":
    main()
