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

from neutron_lib import constants as n_const
from oslo_log import log

from dragonflow.common import exceptions
from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.controller import port_locator
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import trunk

LOG = log.getLogger(__name__)


class TrunkApp(df_base_app.DFlowApp):

    @df_base_app.register_event(trunk.ChildPortSegmentation,
                                model_constants.EVENT_CREATED)
    def _child_port_segmentation_created(self, child_port_segmentation):
        parent_port = child_port_segmentation.parent
        parent_binding = port_locator.get_port_binding(parent_port)
        if parent_binding is None:
            return

        if parent_binding.is_local:
            self._install_local_cps(child_port_segmentation)
        else:
            self._install_remote_cps(child_port_segmentation)

    def _install_local_cps(self, child_port_segmentation):
        self._add_classification_rule(child_port_segmentation)
        self._add_dispatch_rule(child_port_segmentation)
        port_locator.copy_port_binding(
            child_port_segmentation.port,
            child_port_segmentation.parent,
        )
        child_port_segmentation.port.emit_bind_local()

    def _install_remote_cps(self, child_port_segmentation):
        port_locator.copy_port_binding(
            child_port_segmentation.port,
            child_port_segmentation.parent,
        )
        child_port_segmentation.port.emit_bind_remote()

    def _get_classification_params_vlan(self, child_port_segmentation):
        vlan_vid = (self.ofproto.OFPVID_PRESENT |
                    child_port_segmentation.segmentation_id)
        return {'vlan_vid': vlan_vid}

    def _get_classification_match(self, child_port_segmentation):
        params = {'reg6': child_port_segmentation.parent.unique_key}
        segmentation_type = child_port_segmentation.segmentation_type
        if n_const.TYPE_VLAN == segmentation_type:
            params.update(
                self._get_classification_params_vlan(child_port_segmentation),
            )
        else:
            raise exceptions.UnsupportedSegmentationType(
                    segmentation_type=segmentation_type)
        return self.parser.OFPMatch(**params)

    def _add_classification_actions_vlan(self,
                                         actions, child_port_segmentation):
        actions.append(self.parser.OFPActionPopVlan())

    def _get_classification_actions(self, child_port_segmentation):
        segmentation_type = child_port_segmentation.segmentation_type
        lport = child_port_segmentation.port
        network_id = lport.lswitch.unique_key
        unique_key = lport.unique_key
        # TODO(oanson) This code is very similar to classifier app.
        actions = [
            self.parser.OFPActionSetField(reg6=unique_key),
            self.parser.OFPActionSetField(metadata=network_id),
        ]
        if n_const.TYPE_VLAN == segmentation_type:
            self._add_classification_actions_vlan(actions,
                                                  child_port_segmentation)
        else:
            raise exceptions.UnsupportedSegmentationType(
                segmentation_type=segmentation_type
            )

        actions.append(self.parser.NXActionResubmit())
        return actions

    def _add_classification_rule(self, child_port_segmentation):
        match = self._get_classification_match(child_port_segmentation)
        actions = self._get_classification_actions(child_port_segmentation)
        self.mod_flow(
            table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            actions=actions,
        )

    def _add_dispatch_rule(self, child_port_segmentation):
        match = self._get_dispatch_match(child_port_segmentation)
        actions = self._get_dispatch_actions(child_port_segmentation)
        self.mod_flow(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            actions=actions,
        )

    def _get_dispatch_match(self, child_port_segmentation):
        lport = child_port_segmentation.port
        match = self.parser.OFPMatch(reg7=lport.unique_key)
        return match

    def _add_dispatch_actions_vlan(self, actions, child_port_segmentation):
        vlan_tag = (child_port_segmentation.segmentation_id |
                    self.ofproto.OFPVID_PRESENT)
        actions.extend((self.parser.OFPActionPushVlan(),
                        self.parser.OFPActionSetField(vlan_vid=vlan_tag)))
        LOG.info("trunk_app:_add_dispatch_actions_vlan: Setting vlan_id: %s",
                 hex(vlan_tag))

    def _get_dispatch_actions(self, child_port_segmentation):
        actions = []
        segmentation_type = child_port_segmentation.segmentation_type
        if n_const.TYPE_VLAN == segmentation_type:
            self._add_dispatch_actions_vlan(actions, child_port_segmentation)
        else:
            raise exceptions.UnsupportedSegmentationType(
                segmentation_type=segmentation_type
            )

        parent_port_key = child_port_segmentation.parent.unique_key

        actions += [
            self.parser.OFPActionSetField(reg7=parent_port_key),
            self.parser.NXActionResubmit(),
        ]
        return actions

    @df_base_app.register_event(trunk.ChildPortSegmentation,
                                model_constants.EVENT_DELETED)
    def _child_port_segmentation_deleted(self, child_port_segmentation):
        parent_port = child_port_segmentation.parent
        parent_binding = port_locator.get_port_binding(parent_port)
        if parent_binding is None:
            return

        if parent_binding.is_local:
            self._uninstall_local_cps(child_port_segmentation)
        else:
            self._uninstall_remote_cps(child_port_segmentation)

    def _uninstall_local_cps(self, child_port_segmentation):
        child_port_segmentation.port.emit_unbind_local()
        port_locator.clear_port_binding(child_port_segmentation.port)
        self._delete_classification_rule(child_port_segmentation)
        self._delete_dispatch_rule(child_port_segmentation)

    def _uninstall_remote_cps(self, child_port_segmentation):
        child_port_segmentation.port.emit_unbind_remote()
        port_locator.clear_port_binding(child_port_segmentation.port)

    def _delete_classification_rule(self, child_port_segmentation):
        match = self._get_classification_match(child_port_segmentation)
        self.mod_flow(
            table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=match,
            command=self.ofproto.OFPFC_DELETE_STRICT,
        )

    def _delete_dispatch_rule(self, child_port_segmentation):
        match = self._get_dispatch_match(child_port_segmentation)
        self.mod_flow(
            table_id=constants.INGRESS_DISPATCH_TABLE,
            priority=constants.PRIORITY_MEDIUM,
            match=match,
            command=self.ofproto.OFPFC_DELETE_STRICT,
        )

    def _get_all_cps_by_parent(self, lport):
        return self.db_store.get_all(
            trunk.ChildPortSegmentation(parent=lport.id),
            index=trunk.ChildPortSegmentation.get_index('parent_id'),
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _local_port_bound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._install_local_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _local_port_unbound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._uninstall_local_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    def _remote_port_bound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._install_remote_cps(cps)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    def _remote_port_unbound(self, lport):
        for cps in self._get_all_cps_by_parent(lport):
            self._uninstall_remote_cps(cps)
