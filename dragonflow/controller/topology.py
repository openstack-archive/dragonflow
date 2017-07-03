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

import collections

from neutron_lib import constants as n_const
from oslo_log import log

from dragonflow.common import constants
from dragonflow.db import db_store
from dragonflow.db.models import l2
from dragonflow.db.models import migration
from dragonflow.db.models import ovs

LOG = log.getLogger(__name__)


# This tuple is used as the key for ovs_to_lport_mapping, which maps an OVS
# port to its Logical Port. lport_id is the Logical Port's ID. topic is the
# tenant (or project).
OvsLportMapping = collections.namedtuple('OvsLportMapping',
                                         ('lport_id', 'topic'))


class Topology(object):

    def __init__(self, controller, enable_selective_topology_distribution):
        self.ovs_port_type = (constants.OVS_VM_INTERFACE,
                              constants.OVS_TUNNEL_INTERFACE,
                              constants.OVS_PATCH_INTERFACE)

        # Stores topics(tenants) subscribed by lports in the current local
        # controller. I,e, {tenant1:{lport1, lport2}, tenant2:{lport3}}
        self.topic_subscribed = {}
        self.enable_selective_topo_dist = \
            enable_selective_topology_distribution
        self.ovs_ports = {}
        self.ovs_to_lport_mapping = {}

        self.controller = controller
        self.nb_api = controller.get_nb_api()
        self.chassis_name = controller.get_chassis_name()
        self.db_store = db_store.get_instance()

        ovs.OvsPort.register_created(self.ovs_port_updated)
        ovs.OvsPort.register_updated(self.ovs_port_updated)
        ovs.OvsPort.register_deleted(self.ovs_port_deleted)

    def ovs_port_updated(self, ovs_port, orig_ovs_port=None):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entry port to process
        port online/update event

        @param ovs_port:
        @return : None
        """
        if ovs_port is None:
            LOG.error("ovs_port is None")
            return
        LOG.info("Ovs port updated: %s", ovs_port)
        # ignore port that misses some parameters
        if not self._check_ovs_port_integrity(ovs_port):
            return
        port_id = ovs_port.id
        old_port = self.ovs_ports.get(port_id)
        if old_port is None:
            action = "added"
        else:
            action = 'updated'

        self.ovs_ports[port_id] = ovs_port
        port_type = ovs_port.type
        if port_type not in self.ovs_port_type:
            LOG.info("Unmanaged port online: %s", ovs_port)
            return

        handler_name = '_' + port_type + '_port_' + action

        try:
            handler = getattr(self, handler_name, None)
            if handler is not None:
                handler(ovs_port)
        except Exception:
            LOG.exception(
                "Exception occurred when handling port online event")

    def ovs_port_deleted(self, ovs_port):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entrance port to process
        port offline event

        @param ovs_port:
        @return : None
        """
        ovs_port = self.ovs_ports.get(ovs_port.id)
        if ovs_port is None:
            return

        port_type = ovs_port.type
        if port_type not in self.ovs_port_type:
            LOG.info("Unmanaged port offline: %s", ovs_port)
            return

        handler_name = '_' + port_type + '_port_deleted'

        try:
            handler = getattr(self, handler_name, None)
            if handler is not None:
                handler(ovs_port)
            else:
                LOG.info("%s is None.", handler_name)
        except Exception:
            LOG.exception("Exception occurred when handling "
                          "ovs port update event")
        finally:
            del self.ovs_ports[ovs_port.id]

    def _check_ovs_port_integrity(self, ovs_port):
        """
        There are some cases that some para of ovs port is missing
        then the event will be discarded
        """

        ofport = ovs_port.ofport
        port_type = ovs_port.type

        if (ofport is None) or (ofport < 0) or (port_type is None):
            return False

        if (port_type == constants.OVS_VM_INTERFACE and
                ovs_port.lport is None):
            return False

        return True

    def _tunnel_port_added(self, ovs_port):
        self._tunnel_port_updated(ovs_port)

    def _process_ovs_tunnel_port(self, ovs_port, action):
        tunnel_type = ovs_port.tunnel_type
        if not tunnel_type:
            return

        lswitches = self.db_store.get_all(
            l2.LogicalSwitch(network_type=tunnel_type),
            l2.LogicalSwitch.get_index('network_type'))
        for lswitch in lswitches:
            index = l2.LogicalPort.get_index('lswitch_id')
            lports = self.db_store.get_all(l2.LogicalPort(lswitch=lswitch),
                                           index=index)
            for lport in lports:
                if lport.is_local:
                    continue

                # Update of virtual tunnel port should update remote port in
                # the lswitch of same type.
                try:
                    if action == "set":
                        self.controller.update(lport)
                    else:
                        self.controller.delete(lport)
                except Exception:
                    LOG.exception("Failed to process logical port"
                                  "when %(action)s tunnel %(lport)s",
                                  {'action': action, 'lport': lport})

    def _tunnel_port_updated(self, ovs_port):
        self._process_ovs_tunnel_port(ovs_port, "set")

    def _tunnel_port_deleted(self, ovs_port):
        self._process_ovs_tunnel_port(ovs_port, "delete")

    def _vm_port_added(self, ovs_port):
        self._vm_port_updated(ovs_port)
        self.controller.notify_port_status(
            ovs_port, n_const.PORT_STATUS_ACTIVE)

    def _vm_port_updated(self, ovs_port):
        lport = self._get_lport(ovs_port)
        if lport is None:
            LOG.warning("No logical port found for ovs port: %s",
                        ovs_port)
            return
        topic = lport.topic
        if not topic:
            return
        self._add_to_topic_subscribed(topic, lport.id)

        self.ovs_to_lport_mapping[ovs_port.id] = OvsLportMapping(
                lport_id=lport.id, topic=topic)

        chassis = lport.binding.chassis
        # check if migration occurs
        if chassis.id != self.chassis_name:
            device_owner = lport.device_owner
            if n_const.DEVICE_OWNER_COMPUTE_PREFIX in device_owner:
                LOG.info("Prepare migrate lport %(lport)s to %(chassis)s",
                         {"lport": lport.id, "chassis": chassis})
                self.nb_api.create(migration.Migration(
                        id=lport.id, dest_chassis=self.chassis_name,
                        status=migration.MIGRATION_STATUS_DEST_PLUG))
            return

        cached_lport = ovs_port.lport.get_object()
        if not cached_lport:
            # If the logical port is not in db store it has not been applied
            # to dragonflow apps. We need to update it in dragonflow controller
            LOG.info("A local logical port(%s) is online", lport)
            try:
                self.controller.update(lport)
            except Exception:
                LOG.exception('Failed to process logical port online '
                              'event: %s', lport)

    def _vm_port_deleted(self, ovs_port):
        ovs_port_id = ovs_port.id
        lport_ref = ovs_port.lport
        lport = lport_ref.get_object()
        if lport is None:
            lport = self.ovs_to_lport_mapping.get(ovs_port_id)
            if lport is None:
                return
            topic = lport.topic
            del self.ovs_to_lport_mapping[ovs_port_id]
            self._del_from_topic_subscribed(topic, lport.id)
            return

        topic = lport.topic

        LOG.info("The logical port(%s) is offline", lport)
        try:
            self.controller.delete(lport)
        except Exception:
            LOG.exception('Failed to process logical port offline event %s',
                          lport_ref.id)
        finally:
            self.controller.notify_port_status(
                ovs_port, n_const.PORT_STATUS_DOWN)

            migration_obj = self.nb_api.get(
                    migration.Migration(id=lport_ref.id))
            if migration_obj and migration_obj.chassis:
                LOG.info("Sending migrating event for %s", lport_ref.id)
                migration_obj.lport = lport_ref
                migration_obj.status = migration.MIGRATION_STATUS_SRC_UNPLUG
                self.nb_api.update(migration_obj)

            del self.ovs_to_lport_mapping[ovs_port_id]
            self._del_from_topic_subscribed(topic, lport_ref.id)

    def _add_to_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist or not topic:
            return

        if topic not in self.topic_subscribed:
            LOG.info("Subscribe topic: %(topic)s by lport: %(id)s",
                     {"topic": topic, "id": lport_id})
            self.controller.register_topic(topic)
            self.topic_subscribed[topic] = set([lport_id])
        else:
            self.topic_subscribed[topic].add(lport_id)

    def _del_from_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist or not topic:
            return
        port_ids = self.topic_subscribed[topic]
        port_ids.remove(lport_id)
        if len(port_ids) == 0:
            LOG.info("Unsubscribe topic: %(topic)s by lport: %(id)s",
                     {"topic": topic, "id": lport_id})
            del self.topic_subscribed[topic]
            self.controller.unregister_topic(topic)

    def get_subscribed_topics(self):
        if not self.enable_selective_topo_dist:
            # Just return None when enable_selective_topo_dist is False
            return

        # Return the actual topics that are subscribed. It could be empty
        # set, which represents no topic is subscribed now.
        return set(self.topic_subscribed)

    def _get_lport(self, ovs_port):
        if not ovs_port.lport:
            return None
        lport = ovs_port.lport.get_object()
        if lport is None:
            lport = self.nb_api.get(ovs_port.lport)
        return lport

    def check_topology_info(self):
        """
        In order to prevent the situation that the connection between
        df controller and df db break down, we should recheck the local
        ovs ports to make sure all the topics of these ovs ports could
        be subscribed and all the vms could work well.
        """
        new_ovs_to_lport_mapping = {}
        add_ovs_to_lport_mapping = {}
        delete_ovs_to_lport_mapping = self.ovs_to_lport_mapping
        for key, ovs_port in self.ovs_ports.items():
            if ovs_port.type == constants.OVS_VM_INTERFACE:
                lport = self._get_lport(ovs_port)
                if lport is None:
                    LOG.warning("No logical port found for ovs port: %s",
                                ovs_port)
                    continue
                topic = lport.topic
                if not topic:
                    continue
                new_ovs_to_lport_mapping[key] = OvsLportMapping(
                    lport_id=lport.id, topic=topic)
                if not delete_ovs_to_lport_mapping.pop(key, None):
                    add_ovs_to_lport_mapping[key] = OvsLportMapping(
                        lport_id=lport.id, topic=topic)
        self.ovs_to_lport_mapping = new_ovs_to_lport_mapping
        for value in add_ovs_to_lport_mapping.values():
            lport_id = value.lport_id
            topic = value.topic
            self._add_to_topic_subscribed(topic, lport_id)

        for value in delete_ovs_to_lport_mapping.values():
            lport_id = value.lport_id
            topic = value.topic
            self._del_from_topic_subscribed(topic, lport_id)
