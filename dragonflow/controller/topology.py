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

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI, _LE, _LW
from dragonflow.common import constants
from dragonflow.controller import df_db_objects_refresh
from dragonflow.db import models as db_models

LOG = log.getLogger(__name__)


class Topology(object):

    def __init__(self, controller, enable_selective_topology_distribution):
        self.ovs_port_type = (db_models.OvsPort.TYPE_VM,
                              db_models.OvsPort.TYPE_TUNNEL,
                              db_models.OvsPort.TYPE_PATCH,
                              db_models.OvsPort.TYPE_BRIDGE)

        # Stores topics(tenants) subscribed by lports in the current local
        # controller. I,e, {tenant1:{lport1, lport2}, tenant2:{lport3}}
        self.topic_subscribed = {}
        self.enable_selective_topo_dist = \
            enable_selective_topology_distribution
        self.ovs_ports = {}
        self.ovs_to_lport_mapping = {}

        self.controller = controller
        self.nb_api = controller.get_nb_api()
        self.port_status_reporter = controller.get_portstatus_notifier()
        self.db_store = controller.get_db_store()
        self.openflow_app = controller.get_openflow_app()
        self.chassis_name = controller.get_chassis_name()

    def ovs_port_updated(self, ovs_port):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entry port to process
        port online/update event

        @param ovs_port:
        @return : None
        """
        if ovs_port is None:
            LOG.error(_LE("ovs_port is None"))
            return
        LOG.info(_LI("Ovs port updated: %s") % str(ovs_port))
        port_id = ovs_port.get_id()
        old_port = self.ovs_ports.get(port_id)
        if old_port is None:
            # ignore new port that misses some parameters
            if not self._check_ovs_port_integrity(ovs_port):
                return
            else:
                action = "added"
        else:
            action = 'updated'

        self.ovs_ports[port_id] = ovs_port
        port_type = ovs_port.get_type()
        if port_type not in self.ovs_port_type:
            LOG.info(_LI("Unmanaged port online: %s"), ovs_port)
            return

        handler_name = '_' + port_type + '_port_' + action

        try:
            handler = getattr(self, handler_name, None)
            if handler is not None:
                handler(ovs_port)
        except Exception:
            LOG.exception(_LE(
                "Exception occurred when handling port online event"))

    def ovs_port_deleted(self, ovs_port_id):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entrance port to process
        port offline event

        @param ovs_port_id:
        @return : None
        """
        ovs_port = self.ovs_ports.get(ovs_port_id)
        if ovs_port is None:
            return

        port_type = ovs_port.get_type()
        if port_type not in self.ovs_port_type:
            LOG.info(_LI("Unmanaged port offline: %s"), ovs_port)
            return

        handler_name = '_' + port_type + '_port_deleted'

        try:
            handler = getattr(self, handler_name, None)
            if handler is not None:
                handler(ovs_port)
            else:
                LOG.info(_LI("%s is None."), handler_name)
        except Exception:
            LOG.exception(_LE("Exception occurred when handling "
                          "ovs port update event"))
        finally:
            del self.ovs_ports[ovs_port_id]

    def _check_ovs_port_integrity(self, ovs_port):
        """
        There are some cases that some para of ovs port is missing
        then the event will be discarded
        """

        ofport = ovs_port.get_ofport()
        port_type = ovs_port.get_type()

        if (ofport is None) or (ofport < 0) or (port_type is None):
            return False

        if (port_type == db_models.OvsPort.TYPE_VM and
                ovs_port.get_iface_id() is None):
            return False

        return True

    def _tunnel_port_added(self, ovs_port):
        self._tunnel_port_updated(ovs_port)

    def _process_ovs_tunnel_port(self, ovs_port, action):
        tunnel_type = ovs_port.get_tunnel_type()
        if not tunnel_type:
            return

        lswitch_ids = self.db_store.get_lswitch_keys_by_network_type(
            tunnel_type)
        for lswitch_id in lswitch_ids:
            lports = self.db_store.get_ports_by_network_id(lswitch_id)
            for lport in lports:
                if lport.get_external_value('is_local'):
                    continue

                # Update of virtual tunnel port should update remote port in
                # the lswitch of same type.
                try:
                    if action == "set":
                        self.controller.update_lport(lport)
                    else:
                        self.controller.delete_lport(lport.get_id())
                except Exception:
                    LOG.exception(_LE("Failed to process logical port"
                                      "when %(action)s tunnel %(lport)s"),
                                  {'action': action, 'lport': lport})

    def _tunnel_port_updated(self, ovs_port):
        self._process_ovs_tunnel_port(ovs_port, "set")

    def _tunnel_port_deleted(self, ovs_port):
        self._process_ovs_tunnel_port(ovs_port, "delete")

    def _vm_port_added(self, ovs_port):
        self._vm_port_updated(ovs_port)
        # publish vm port up event
        if cfg.CONF.df.enable_port_status_notifier:
            self.port_status_reporter.notify_port_status(
                ovs_port, constants.PORT_STATUS_UP)

    def _vm_port_updated(self, ovs_port):
        lport_id = ovs_port.get_iface_id()
        lport = self._get_lport(lport_id)
        if lport is None:
            LOG.warning(_LW("No logical port found for ovs port: %s")
                        % str(ovs_port))
            return
        topic = lport.get_topic()
        if not topic:
            return
        self._add_to_topic_subscribed(topic, lport_id)

        ovs_port_id = ovs_port.get_id()
        self.ovs_to_lport_mapping[ovs_port_id] = {'lport_id': lport_id,
                                                  'topic': topic}

        cached_lport = self.db_store.get_port(lport_id)
        if not cached_lport or not cached_lport.get_external_value("ofport"):
            # If the logical port is not in db store or its ofport is not
            # valid. It has not been applied to dragonflow apps. We need to
            # update it in dragonflow controller.
            LOG.info(_LI("A local logical port(%s) is online"), lport)
            try:
                self.controller.update_lport(lport)
            except Exception:
                LOG.exception(_LE('Failed to process logical port online '
                                  'event: %s'), lport)

    def _bridge_port_added(self, ovs_port):
        self._bridge_port_updated(ovs_port)

    def _bridge_port_updated(self, ovs_port):
        try:
            self.controller.bridge_port_updated(ovs_port)
        except Exception:
            LOG.exception(_LE('Failed to process bridge port online '
                              'event: %s') % str(ovs_port))

    def _vm_port_deleted(self, ovs_port):
        ovs_port_id = ovs_port.get_id()
        lport_id = ovs_port.get_iface_id()
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            lport = self.ovs_to_lport_mapping.get(ovs_port_id)
            if lport is None:
                return
            topic = lport.get('topic')
            del self.ovs_to_lport_mapping[ovs_port_id]
            self._del_from_topic_subscribed(topic, lport_id)
            return

        topic = lport.get_topic()

        LOG.info(_LI("The logical port(%s) is offline") % str(lport))
        try:
            self.controller.delete_lport(lport_id)
        except Exception:
            LOG.exception(_LE(
                'Failed to process logical port offline event %s') % lport_id)
        finally:
            # publish vm port down event.
            if cfg.CONF.df.enable_port_status_notifier:
                self.port_status_reporter.notify_port_status(
                    ovs_port, constants.PORT_STATUS_DOWN)

            del self.ovs_to_lport_mapping[ovs_port_id]
            self._del_from_topic_subscribed(topic, lport_id)

    def _add_to_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist or not topic:
            return

        if topic not in self.topic_subscribed:
            LOG.info(_LI("Subscribe topic: %(topic)s by lport: %(id)s") %
                     {"topic": topic, "id": lport_id})
            self.nb_api.subscriber.register_topic(topic)
            self._pull_tenant_topology_from_db(topic)
            self.topic_subscribed[topic] = set([lport_id])
        else:
            self.topic_subscribed[topic].add(lport_id)

    def _del_from_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist or not topic:
            return
        port_ids = self.topic_subscribed[topic]
        port_ids.remove(lport_id)
        if len(port_ids) == 0:
            LOG.info(_LI("Unsubscribe topic: %(topic)s by lport: %(id)s") %
                     {"topic": topic, "id": lport_id})
            del self.topic_subscribed[topic]
            self.nb_api.subscriber.unregister_topic(topic)
            self._clear_tenant_topology(topic)

    def get_subscribed_topics(self):
        if not self.enable_selective_topo_dist:
            # Just return None when enable_selective_topo_dist is False
            return

        # Return the actual topics that are subscribed. It could be empty
        # set, which represents no topic is subscribed now.
        return set(self.topic_subscribed)

    def _pull_tenant_topology_from_db(self, tenant_id):
        df_db_objects_refresh.sync_local_cache_from_nb_db({tenant_id})

    def _clear_tenant_topology(self, tenant_id):
        df_db_objects_refresh.clear_local_cache({tenant_id})

    def _get_lport(self, port_id, topic=None):
        lport = self.db_store.get_port(port_id)
        if lport is None:
            lport = self.nb_api.get_logical_port(port_id, topic)

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
            if ovs_port.get_type() == db_models.OvsPort.TYPE_VM:
                lport_id = ovs_port.get_iface_id()
                lport = self._get_lport(lport_id)
                if lport is None:
                    LOG.warning(_LW("No logical port found for ovs port: %s"),
                                ovs_port)
                    continue
                topic = lport.get_topic()
                if not topic:
                    continue
                new_ovs_to_lport_mapping[key] = {
                    'lport_id': lport_id, 'topic': topic}
                if not delete_ovs_to_lport_mapping.pop(key, None):
                    add_ovs_to_lport_mapping[key] = {
                        'lport_id': lport_id, 'topic': topic}
        self.ovs_to_lport_mapping = new_ovs_to_lport_mapping
        for value in add_ovs_to_lport_mapping.values():
            lport_id = value['lport_id']
            topic = value['topic']
            self._add_to_topic_subscribed(topic, lport_id)

        for value in delete_ovs_to_lport_mapping.values():
            lport_id = value['lport_id']
            topic = value['topic']
            self._del_from_topic_subscribed(topic, lport_id)
