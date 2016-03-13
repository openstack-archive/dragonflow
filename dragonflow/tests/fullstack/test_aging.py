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
import signal
import time

from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import test_base

from oslo_log import log

from subprocess import Popen, PIPE

DRAGONFLOW_ENTRANCE = "df_local_controller.py"
DRAGONFLOW_PATH =\
    '/opt/stack/dragonflow/dragonflow/controller/df_local_controller.py'
DF_WAIT_SECONDS = 10

LOG = log.getLogger(__name__)


class TestAging(test_base.DFTestBase):

    def setUp(self):
        super(TestAging, self).setUp()

    def kill_dragonflow(self):
        process = Popen(['ps', '-eo', 'pid,args'], stdout=PIPE, stderr=PIPE)
        stdout, notused = process.communicate()
        for line in stdout.splitlines():
            pid, cmdline = line.strip().split(' ', 1)
            if DRAGONFLOW_ENTRANCE in cmdline:
                os.kill(int(pid), signal.SIGTERM)

    def start_dragonflow(self):
        Popen([
            'python',
            DRAGONFLOW_PATH,
            '--config-file',
            '/etc/neutron/neutron.conf'
        ], stdout=PIPE, stderr=PIPE, close_fds=True)

    def test_dragonflow_restart(self):
        ovs = test_utils.OvsFlowsParser()
        old_flow = ovs.dump()
        LOG.debug("flow cookie is %s", old_flow[0]['cookie'])
        old_cookie = int(old_flow[0]['cookie'], 16)
        expect_cookie = old_cookie ^ 0x1

        self.kill_dragonflow()
        LOG.debug("dragonflow is killed")
        time.sleep(DF_WAIT_SECONDS)
        self.start_dragonflow()
        time.sleep(DF_WAIT_SECONDS)
        new_flow = ovs.dump()
        LOG.debug("flow cookie is %s", new_flow[0]['cookie'])
        new_cookie = int(new_flow[0]['cookie'], 16)
        self.assertEqual(new_cookie, expect_cookie)
