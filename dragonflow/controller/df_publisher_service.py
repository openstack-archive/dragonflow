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

from Queue import Queue
import sys

from oslo_config import cfg
from oslo_log import log as logging

from neutron.agent.common import config
from neutron.common import config as common_config

from dragonflow._i18n import _LW
from dragonflow.common import common_params
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common

eventlet.monkey_patch()

LOG = logging.getLogger(__name__)


class PublisherService(object):
    def __init__(self):
        self.queue = Queue()
        self.publisher = self._get_publisher()
        self.multiproc_subscriber = self._get_multiproc_subscriber()

    def _get_publisher(self):
        pub_sub_driver = df_utils.load_driver(
                                    cfg.CONF.df.pub_sub_driver,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_publisher()

    def _get_multiproc_subscriber(self):
        pub_sub_driver = df_utils.load_driver(
                                    cfg.CONF.df.pub_sub_local_driver,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_subscriber()

    def initialize(self):
        if self.multiproc_subscriber:
            self.multiproc_subscriber.initialize(self._append_event_to_queue)
        self.remote_publisher.initialize()
        # TODO(oanson) TableMonitor initialisation goes here

    def _append_event_to_queue(self, table, key, action, value, topic):
        event = db_common.DbUpdate(table, key, action, value, topic=topic)
        self._queue.put(event)

    def run(self):
        if self.multiproc_subscriber:
            self.multiproc_subscriber.daemonize()
        # TODO(oanson) TableMonitor daemonize will go here
        while True:
            try:
                event = self._queue.get()
                self.remote_publisher.send_event(event)
            except Exception as e:
                LOG.warning(_LW("Exception in main loop: {}, {}").format(
                    e, sys.exc_info()[2]
                ))
                # Ignore


def main():
    cfg.CONF.register_opts(common_params.df_opts, 'df')
    common_config.init(sys.argv[1:])
    config.setup_logging()
    service = PublisherService()
    service.initialize()
    service.run()

if __name__ == "__main__":
    main()
