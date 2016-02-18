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

#
#    work to be done:
#       add tenant id field in each table
#       add lswitch id in subnet table
#       format the naming of method in nb_api
#

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LI, _LE

LOG = log.getLogger(__name__)


class Topology(object):

    def __init__(self, controller):
        self.ovs_port_type = ('vm', 'tunnel', 'patch', 'bridge')

        # Stores topics(tenants) subscribed by lports in the current local
        # controller. I,e, {tenant1:[lport1, lport2], tenant2:[lport3]}
        self.topic_subscribed = {}
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topo_dist
        self.ovs_ports = {}

        self.controller = controller
        self.nb_api = controller.get_nb_api()
        self.db_store = controller.get_db_store()
        self.openflow_app = controller.get_openflow_app()
        self.chassis_name = controller.get_chassis_name()

    def ovs_port_updated(self, ovs_port):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entrance port to process
        port online event

        @param ovs_port:
        @return : None
        """

        assert ovs_port is not None, "ovs_port is None"
        # there are some cases that some para of ovs port is missing
        # then the event will be discarded
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
            LOG.error(_LE("Unknown port online: ") + ovs_port)
            return

        handler_name = '_' + port_type + '_port_' + action

        try:
            handler = self.__getattribute__(handler_name)
            handler(ovs_port)
        except Exception as e:
            LOG.error(_LE(
                "exception occurred when handling port online event"))
            LOG.error(e)

    def ovs_port_deleted(self, ovs_port_id):

        ovs_port = self.ovs_ports.get(ovs_port_id)
        if ovs_port is None:
            return

        port_type = ovs_port.get_type()
        if port_type not in self.ovs_port_type:
            LOG.error(_LE("Unknown port offline: ") + ovs_port)
            return

        handler_name = '_' + port_type + '_deleted'

        try:
            handler = self.__getattribute__(handler_name)
            handler(ovs_port)
        except Exception as e:
            LOG.error(_LE("exception occurred when handling "
                          "port offline event"))
            LOG.error(e)
        finally:
            self.ovs_ports.pop(ovs_port_id)

    def _check_ovs_port_integrity(self, ovs_port):
        # todo(duankebo) verify the integrity of parameter
        return True

    def _vm_port_added(self, ovs_port):
        lport_id = ovs_port.get_iface_id()
        lport = self._get_lport(lport_id)
        assert lport is not None, "Port:{id} not found".format(id=lport_id)

        tenant_id = lport.get_tenant_id()
        self._add_to_topic_subscribed(tenant_id, lport.get_id())

        # update lport, notify apps
        lport.set_external_value('ofport', ovs_port.get_ofport())
        lport.set_external_value('is_local', True)
        lport.set_external_value('ovs_port_id', ovs_port.get_id())
        LOG.info(_LI("Adding new local Logical Port = %s") % lport.__str__())

        self.ovs_ports[ovs_port.get_id()] = ovs_port

        try:
            self.open_flow_app.notify_local_vm_port_added(lport)
        except Exception:
            LOG.error(_LE('app failed to process vm port online event {%s} ')
                      % lport.__str__())
        finally:
            self.db_store.set_port(lport.get_id(), lport, True)
            # todo(update lport need a tenant parameter)
            self.nb_api.update_lport(lport_id, chassis=self.chassis_name,
                                     status='ACTIVE')

    def _vm_port_updated(self, ovs_port):
        self.ovs_ports[ovs_port.get_id()] = ovs_port

    def _vm_port_deleted(self, ovs_port):
        ovs_port_id = ovs_port['type']
        lport = self._get_lport(ovs_port_id)
        assert lport is not None, "Port:{id} not found".format(id=ovs_port_id)

        lport_id = lport.get_id()
        tenant_id = lport.get_tenant_id()

        LOG.info(_LI("Vm port(%s) offline") % lport)
        # todo(duankebo), notify apps.
        try:
            self.openflow_app.notify_local_vm_port_deleted(lport)
        except Exception:
            LOG.error(_LE('app failed to process vm port offline event {%s} ')
                      % lport.__str__())
        finally:
            # todo(duankebo) lock db
            lport = self.nb_api.get_logical_port(lport_id)
            if lport.get_chassis() == self.chassis_name:
                self.nb_api.update_lport(lport.get_id(), chassis=None,
                                         status='DOWN')

            self.db_store.del_port(lport_id)
            self._del_from_topic_subscribed(tenant_id, lport_id)

    def _patch_port_added(self, ovs_port):
        pass

    def _patch_port_updated(self, ovs_port):
        pass

    def _patch_port_deleted(self, ovs_port_id):
        pass

    def _tunnel_port_added(self, ovs_port):
        pass

    def _tunnel_port_updated(self, ovs_port):
        pass

    def _tunnel_port_deleted(self, ovs_port_id):
        pass

    def _bridge_port_added(self, ovs_port):
        pass

    def _bridge_port_updated(self, ovs_port):
        pass

    def _bridge_port_deleted(self, ovs_port_id):
        pass

    def _add_to_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist:
            return

        if topic not in self.topic_subscribed:
            self._pull_tenant_topology_from_db(topic)
            self.nb_api.subscriber.register_topic(topic)
            self.topic_subscribed[topic] = [lport_id]
        else:
            self.topic_subscribed[topic].append(lport_id)

    def _del_from_topic_subscribed(self, topic, lport_id):
        if not self.enable_selective_topo_dist:
            return
        port_ids = self.topic_subscribed[topic]
        port_ids.pop(lport_id)
        if len(port_ids) == 0:
            self.topic_subscribed.pop(topic)
            self.nb_api.subscriber.unregister_topic(topic)

    def _pull_tenant_topology_from_db(self, tenant_id):
        ports = self.nb_api.get_all_logical_ports(tenant_id)
        for port in ports:
            self.controller.logical_port_updated(port)

        switches = self.nb_api.get_all_logical_switches(tenant_id)
        for switch in switches:
            self.controller.logical_switch_updated(switch)

        routers = self.nb_api.get_routers(tenant_id)
        for router in routers:
            self.controller.router_updated(router)

        sg_groups = self.nb_api.get_security_groups(tenant_id)
        for sg_group in sg_groups:
            self.controller.security_group_updated(sg_group)

        floating_ips = self.nb_api.get_floatingips(tenant_id)
        for floating_ip in floating_ips:
            self.controller.floatingip_updated(floating_ip)

    def _clear_tenant_topology(self, tenant_id):
        ports = self.db_store.get_ports()
        for port in ports:
            if tenant_id == port.get_tenant_id:
                self.controller.logical_port_deleted(port.get_id())

        floating_ips = self.db_store.get_floatingips()
        for floating_ip in floating_ips:
            if tenant_id == floating_ip.get_tenant_id:
                self.controller.floatingip_deleted(floating_ip.get_id())

        switches = self.db_store.get_lswitchs()
        for switch in switches:
            if tenant_id == switch.get_tenant_id:
                self.controller.logical_switch_deleted(switch.get_id())

        routers = self.db_store.get_routers()
        for router in routers:
            if tenant_id == router.get_tenant_id:
                self.controller.router_deleted(router.get_id())

        sg_groups = self.db_store.get_security_groups()
        for sg_group in sg_groups:
            if tenant_id == sg_group.get_tenant_id:
                self.controller.security_group_deleted(sg_group.get_id())

    # def _get_lport(self, port_id, tenant_id=None):
    #
    #     lport = self.db_store.get_port(port_id)
    #
    #     if lport is None:
    #         lport = self.nb_api.get_logical_port(port_id, tenant_id)
    #
    #     return lport
    #
    # def _get_lswitch(self, switch_id, tenant_id=None):
    #     lswitch = self.db_store.get_lswitch(switch_id)
    #
    #     if lswitch is None:
    #         lswitch = self.nb_api.get_lswitch(switch_id, tenant_id)
    #
    #         if lswitch is not None:
    #             self.db_store.set_lswitch(switch_id, lswitch)
    #             self._cache_lswitch(lswitch)
    #
    #     return lswitch
    #
    # def _get_lrouter_by_subnet(self, subnet_id, tenant_id):
    #     routers = self.nb_api.get_all_lrouters(tenant_id)
    #     for router in routers:
    #         subnets = router.get_subnets()
    #         if subnet_id in subnets:
    #             self._cache_lrouter(router, tenant_id)
    #             return router
    #     return None
    #
    # def _cache_lswitch(self, lswitch):
    #     tenant_id = lswitch.get_tenant_id()
    #     switch_id = lswitch.get_id()
    #     tenant_ports = self.nb_api.get_all_logical_ports(tenant_id)
    #
    #     for port in tenant_ports:
    #         if switch_id == port.get_lswitch_id():
    #             self.db_store.set_port(port.get_port_id, port)
    #
    # def _cache_lrouter(self, lrouter, tenant_id):
    #     subnets = lrouter.get_subnets()
    #     for subnet in subnets:
    #         switch_id = subnet.get_switch_id
    #         self._get_lswitch(switch_id, tenant_id)
