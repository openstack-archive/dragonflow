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

from neutron.agent.common import utils
from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.controller.df_base_app import DFlowApp


LOG = log.getLogger(__name__)


class FakeVifApp(DFlowApp):
    def __init__(self, *args, **kwargs):
        super(FakeVifApp, self).__init__(*args, **kwargs)
        self._fake_vifs = {}

    def add_local_port(self, lport):
        if self._check_fakevif_port(lport) is None:
            return
        interfacename = 'tap{}'.format(lport.get_id()[:11])
        LOG.info(_LI("Fake port already created: %s"), interfacename)

    def update_local_port(self, lport, original_lport):
        if self._check_fakevif_port(lport) is None:
            return
        interfacename = 'tap{}'.format(lport.get_id()[:11])
        LOG.info(_LI("Ignoring update for fake port: %s"), interfacename)

    def remove_local_port(self, lport):
        if self._check_fakevif_port(lport) is None:
            return
        bridge = cfg.CONF.df.integration_bridge
        interfacename = 'tap{}'.format(lport.get_id()[:11])
        utils.execute(["ovs-vsctl", "del-port", bridge, interfacename],
                      run_as_root=True, process_input=None)
        LOG.info(_LI("Fake port removed: %s"), interfacename)

    def _check_fakevif_port(self, lport):
        if lport.get_device_owner() != 'fakevif':
            return None
        b_profile = lport.get_binding_profile()
        if b_profile is None:
            return None
        if b_profile['integration_bridge'] != cfg.CONF.df.integration_bridge:
            return None
        return True
