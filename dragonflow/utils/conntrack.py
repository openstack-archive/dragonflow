# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutron.agent.common import utils
from oslo_log import log


LOG = log.getLogger(__name__)


def delete_conntrack_entries_by_filter(ethertype='IPv4', protocol=None,
                                       nw_src=None, nw_dst=None, zone=None):
    cmd = ['conntrack', '-D']
    if protocol:
        cmd.extend(['-p', str(protocol)])
    cmd.extend(['-f', ethertype.lower()])
    if nw_src:
        cmd.extend(['-s', str(nw_src)])
    if nw_dst:
        cmd.extend(['-d', str(nw_dst)])
    if zone:
        cmd.extend(['-w', str(zone)])

    try:
        utils.execute(cmd, run_as_root=True, check_exit_code=True,
                      extra_ok_codes=[1])
        LOG.debug("Successfully executed conntrack command %s", cmd)
    except RuntimeError:
        LOG.exception("Failed execute conntrack command %s", cmd)
