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

import mock
import numpy
import signal
import sys
import time
import uuid

from oslo_log import log
from oslo_utils import importutils

from neutron.common import config as common_config

from dragonflow._i18n import _, _LE
from dragonflow import conf as cfg
from dragonflow.db import api_nb


LOG = log.getLogger(__name__)


df_db_test_opts = [
    cfg.StrOpt('output_folder',
               default=".",
               help=_("The default folder to write output files.")),
    cfg.IntOpt('count',
               default=1000,
               help=_("Create this many elements in the DB for the test.")),
]


def run_server(nb_api):
    topic = str(uuid.uuid4())
    publisher = str(uuid.uuid4())
    lswitch_name = 'lswitch0'
    nb_api.create_publisher(
        publisher,
        topic,
        last_activity_timestamp=time.time()
    )
    nb_api.create_lswitch(lswitch_name, topic)
    start = time.time()
    for idx in range(cfg.CONF.df_db_test.count):
        nb_api.create_lport(
            'lport{}'.format(idx),
            lswitch_name,
            topic,
            timestamp=time.time()
        )
    nb_api.delete_publisher(publisher, topic)
    end = time.time()
    data_str = [str(end - start), str(cfg.CONF.df_db_test.count),
                str(cfg.CONF.df_db_test.count / (end - start))]
    outfile_name = '{}/test_db_server.{}'.format(
        cfg.CONF.df_db_test.output_folder,
        uuid.uuid4()
    )
    outfile = open(outfile_name, 'w')
    outfile.write('total, count, r/sec\n')
    outfile.write(', '.join(data_str))
    outfile.write('\n')
    outfile.close()
    sys.exit(0)


def run_client(nb_api):
    events = []
    start = []

    def generate_status():
        diffs = [now - lport.lport['timestamp']
                 for (now, lport) in events]
        total_time = time.time() - start[0]
        return (
            min(diffs) * 1000,
            max(diffs) * 1000,
            numpy.median(diffs) * 1000,
            numpy.average(diffs) * 1000,
            numpy.mean(diffs) * 1000,
            numpy.std(diffs) * 1000,
            numpy.var(diffs) * 1000,
            sum(diffs),
            total_time,
            len(diffs),
            (len(diffs) / total_time)
        )

    def finished():
        """Print average, median, sum, min, max, etc."""
        data_str = [str(datum) for datum in generate_status()]
        outfile_name = '{}/test_db_client.{}'.format(
            cfg.CONF.df_db_test.output_folder,
            uuid.uuid4()
        )
        outfile = open(outfile_name, 'w')
        outfile.write('min, max, median, average, mean, std, var, sum, '
                      'total, count, r/sec\n')
        outfile.write(', '.join(data_str))
        outfile.write('\n')
        outfile.close()
        sys.exit(0)

    def update_publisher(uuid):
        start.append(time.time())

    def delete_publisher(uuid):
        finished()

    def update_lport(lport):
        events.append((time.time(), lport))

    def signal_handler(signal, frame):
        LOG.error(_LE('You pressed Ctrl+C!'))
        finished()

    def print_status(signal, frame):
        data = generate_status()
        data_str = [str(datum) for datum in data]
        print('min, max, median, average, mean, std, var, sum, count')
        print(", ".join(data_str))

    callback_handler = mock.Mock()
    callback_handler.update_lport = update_lport
    callback_handler.update_publisher = update_publisher
    callback_handler.delete_publisher = delete_publisher
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGUSR1, print_status)
    try:
        nb_api.register_notification_callback(callback_handler)
    except Exception as e:
        LOG.error(_LE('Exception: '), e)
        finished()


def main():
    cfg.CONF.register_opts(df_db_test_opts, 'df_db_test')
    common_config.init(sys.argv[2:])
    # To enable logging, uncomment the following line:
    #common_config.setup_logging()
    nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
    is_server = False
    if sys.argv[1] == 'server':
        is_server = True
    elif sys.argv[1] != 'client':
        raise Exception('Bad parameter #1: Expected \'server\' or \'client\','
                ' found: %s' % sys.argv[1])
    nb_api = api_nb.NbApi(
        nb_driver_class(),
        use_pubsub=cfg.CONF.df.enable_df_pub_sub,
        is_neutron_server=is_server,
    )
    nb_api.initialize(
        db_ip=cfg.CONF.df.remote_db_ip,
        db_port=cfg.CONF.df.remote_db_port,
    )
    if is_server:
        run_server(nb_api)
    else:
        run_client(nb_api)

if __name__ == "__main__":
    main()
