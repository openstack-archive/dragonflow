# Copyright (c) 2015 OpenStack Foundation.
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

from oslo_log import log
from ryu.lib.packet import packet as os_ken_packet

from dragonflow.common import utils as df_utils
from dragonflow.controller import app_base

LOG = log.getLogger(__name__)


@app_base.define_specification(
    states=('main',),
    entrypoints=(
        app_base.Entrypoint(
            name='default',
            target='main',
            consumes=(),
        ),
    ),
    exitpoints=(
        app_base.Exitpoint(
            name='default',
            provides=(),
        ),
    ),
)
class LogPacketApp(app_base.Base):
    def initialize(self):
        self.api.register_table_handler(self.states.main,
                                        self._packet_in_handler)
        self.mod_flow(
            table_id=self.states.main,
            actions=[
                self.parser.OFPActionOutput(self.ofproto.OFPP_CONTROLLER,
                                            self.ofproto.OFPCML_NO_BUFFER),
                self.parser.NXActionResubmitTable(
                        table_id=self.exitpoints.default),
            ]
        )

    def _packet_in_handler(self, event):
        msg = event.msg
        pkt = os_ken_packet.Packet(msg.data)
        LOG.info("LogPacketApp: Got message: %s, match: %s, packet: %s",
                 msg, msg.match, pkt)
