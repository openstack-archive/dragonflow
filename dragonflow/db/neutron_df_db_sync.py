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

from eventlet import greenthread
from oslo_log import log

from neutron import context
from neutron.i18n import _LW

LOG = log.getLogger(__name__)

SYNC_MODE_OFF = 'off'
SYNC_MODE_LOG = 'log'
SYNC_MODE_REPAIR = 'repair'


class DfDbSynchronizer(object):

    def __init__(self, plugin, nb_api, mode):
        self.core_plugin = plugin
        self.nb_api = nb_api
        self.mode = mode

    def sync(self):
        greenthread.spawn_n(self._sync)

    def _sync(self):
        if self.mode == SYNC_MODE_OFF:
            LOG.debug("DF-Neutron DB sync mode is off")
            return

        # Initial delay until service is up
        greenthread.sleep(10)
        LOG.debug("Starting Neutron-DF DB sync process")

        ctx = context.get_admin_context()
        self._sync_networks(ctx)
        self._sync_subnets(ctx)
        self._sync_ports(ctx)
        self._sync_routers(ctx)

    def _sync_networks(self, ctx):
        LOG.debug("DF-Neutron DB sync networks started")

        lswitches = self.nb_api.get_all_logical_switches()
        lswitches_dict = {}
        for lswitch in lswitches:
            lswitches_dict[lswitch.get_id()] = lswitch

        for network in self.core_plugin.get_networks(ctx):
            try:
                net = lswitches_dict.pop(network['id'], None)

                if (self.mode == SYNC_MODE_REPAIR) and (net is None):
                    self.core_plugin.create_network_nb_api(network)

                if self.mode == SYNC_MODE_LOG:
                    if net is None:
                        LOG.warn(_LW("Network found in Neutron but not in DF "
                                     "DB, network_id=%s"),
                                 network['id'])

            except RuntimeError:
                LOG.warn(_LW("Create network failed for "
                             "network %s"), network['id'])

        # TODO(gsagie) Only delete logical switch if it was previously created
        # by neutron
        for lswitch_key in lswitches_dict.keys():
            if self.mode == SYNC_MODE_REPAIR:
                self.nb_api.delete_lswitch(lswitch_key)
            if self.mode == SYNC_MODE_LOG:
                LOG.warn(_LW("Network found in Dragonflow but not in Neutron,"
                             " network_name=%s"), lswitch_key)

        LOG.debug("DF-Neutron DB sync networks finished")

    def _sync_ports(self, ctx):
        LOG.debug("DF-Neutron DB sync ports started")

        lports = self.nb_api.get_all_logical_ports()
        lports_dict = {}
        for lport in lports:
            lports_dict[lport.get_id()] = lport

        for port in self.core_plugin.get_ports(ctx):
            try:
                logical_port = lports_dict.pop(port['id'], None)

                if (self.mode == SYNC_MODE_REPAIR) and (logical_port is None):
                    sgids = self.core_plugin._get_security_groups_on_port(
                        ctx, port)

                    # TODO(gsagie) extract parent name and tag when
                    # supported and pass to 'create_port_in_nb_api'
                    self.core_plugin.create_port_in_nb_api(port,
                                                           None,
                                                           None,
                                                           sgids)

                if self.mode == SYNC_MODE_LOG:
                    if logical_port is None:
                        LOG.warn(_LW("Port found in Neutron but not in DF "
                                     "DB, port_id=%s"),
                                 port['id'])

            except RuntimeError:
                LOG.warn(_LW("Create port failed for"
                             " port %s"), port['id'])

        # Only delete logical port if it was previously created by neutron
        for lport_key in lports_dict.keys():
            if self.mode == SYNC_MODE_REPAIR:
                self.nb_api.delete_lport(lport_key)
            if self.mode == SYNC_MODE_LOG:
                        LOG.warn(_LW("Port found in DF but not in Neutron,"
                                     " port_name=%s"), lport_key)

        LOG.debug("DF-Neutron DB sync ports finished")

    def _sync_subnets(self, ctx):
        # TODO(gsagie) complete this
        pass

    def _sync_routers(self, ctx):
        # TODO(gsagie) complete this
        pass
