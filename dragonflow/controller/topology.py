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


from oslo_log import log

from dragonflow._i18n import _LI, _LW, _LE

from dragonflow.common import constants

LOG = log.getLogger("dragonflow.controller.topology")


class Topology():

    def __init__(self, controller):
        # self.dispatcher = controller.get_dispatcher()
        # self.controller = controller
        self.topic_subscribed = {}
        self.next_network_id = 0

        self.nb_api = controller.get_nb_api()
        self.db_store = controller.get_db_store()
        self.openflow_app = controller.get_openflow_app()
        self.chassis_name = controller.get_chassis_name()
        self.vswitch_api = controller.get_vswitch_api()

    def ovs_port_online(self, ovs_port):
        """
        Changes in ovs port status will be monitored by ovsdb monitor thread
        and notified to topology. This method is the entrance port to process
        port online event

        @param ovs_port:
        @return : None
        """
        # todo(duankebo) parameter of interface and number
        assert ovs_port is not None, "ovs_port is None"

        port_type = ovs_port['type']
        if port_type == 'vm_port':
            handler = self._vm_port_online

        elif port_type == 'tunnel_port':
            handler = self._tunnel_port_online

        elif port_type == 'patch_port':
            handler = self._patch_port_online

        else:
            LOG.error("Unknown port online: " + ovs_port)
            return

        try:
            handler(ovs_port)
        except Exception as e:
            LOG.error(_LE("exception occurred when handling port online event"))
            LOG.error(e)

    def ovs_port_offline(self, ovs_port):

        port_type = ovs_port['type']
        if port_type == 'vm_port':
            handler = self._vm_port_offline

        elif port_type == 'tunnel_port':
            handler = self._tunnel_port_offline

        elif port_type == 'patch_port':
            handler = self._patch_port_offline

        else:
            LOG.error(_LE("Unknown port online: " + ovs_port))
            return

        try:
            handler(ovs_port)
        except Exception as e:
            LOG.error(_LE("exception occurred when handling "
                          "port offline event"))
            LOG.error(e)

    def lport_updated(self, lport):
        """
        Processing northbound add/mod port message.
        @param lport: logical port to be added/modified
        @return: None
        """

        # Chassis is none means the port is created, but not online in some
        # compute node.
        if lport.get_chassis() is None or \
                (lport.get_chassis() == constants.DRAGONFLOW_VIRTUAL_PORT):
            return

        if lport.get_chassis() == self.chassis_name:
            # It is a local port
            # Attention: when this event is processing by the app, lport
            # in the local cache is still the old one or not exist
            self.openflow_app.notify_add_local_port(lport)
            self.db_store.set_port(lport.get_id(), lport, True)
        else:
            # It is a remote port
            # Attention: when this event is processing by the app, lport
            # in the local cache is still the old one or not exist
            self.openflow_app.notify_add_remote_port(lport)
            self.db_store.set_port(lport.get_id(), lport, False)

    def lport_deleted(self, lport_id):
        """
        Processing northbound delete port message.
        @param lport_id: logical port to be deleted
        @return: None
        """

        # Chassis is none means the port is created, but not online in some
        # compute node.
        lport = self.db_store.get_port(lport_id)
        if lport.get_chassis() is None or \
                (lport.get_chassis() == constants.DRAGONFLOW_VIRTUAL_PORT):
            # Delete the incomplete port from local cache
            self.db_store.del_port(lport_id, False)
            return

        if lport.get_chassis() == self.db_store.get_chassis_name():
            # It is a local port
            self.openflow_app.notify_remove_local_port(lport)
            self.db_store.del_port(lport.get_id(), lport, True)
        else:
            # It is a remote port
            self.openflow_app.notify_remove_remote_port(lport)
            self.db_store.del_port(lport.get_id(), lport, False)

    def lswitch_updated(self, lswitch):
        old_lswitch = self.db_store.get_lswitch(lswitch.get_id())
        if old_lswitch == lswitch:
            return

        # Make sure we have a local network_id mapped before we dispatch
        network_id = self._get_network_id(lswitch.get_id())
        lswitch_conf = {'network_id': network_id, 'lswitch': lswitch.__str__()}
        LOG.info(_LI("Adding/Updating Logical Switch = %s") % lswitch_conf)

        self.db_store.set_lswitch(lswitch.get_id(), lswitch)
        self.openflow_app.notify_update_logical_switch(lswitch)

    def lswitch_deleted(self, lswitch_id):
        lswitch = self.db_store.get_lswitch(lswitch_id)
        LOG.info(_LI("Removing Logical Switch = %s") % lswitch.__str__())
        self.openflow_app.notify_remove_logical_switch(lswitch)
        self.db_store.del_lswitch(lswitch_id)
        self.db_store.del_network_id(lswitch_id)

    def lrouter_updated(self, lrouter):
        old_lrouter = self.db_store.get_router(lrouter.get_id())
        if old_lrouter is None:
            LOG.info(_LI("Logical Router created = %s") % lrouter.__str__())
            self._add_new_lrouter(lrouter)
            return

        self._update_lrouter_ports(old_lrouter, lrouter)
        self.db_store.update_router(lrouter.get_id(), lrouter)

    def lrouter_deleted(self, lrouter_id):
        old_lrouter = self.db_store.get_router(lrouter_id)
        if old_lrouter is None:
            return

        old_router_ports = old_lrouter.get_ports()
        for old_port in old_router_ports:
            self._delete_lrouter_port(old_port)
        self.db_store.delete_router(lrouter_id)

    def chassis_created(self, chassis):
        # Check if tunnel already exists to this chassis

        # Create tunnel port to this chassis
        LOG.info(_LI("Adding tunnel to remote chassis = %s") %
                 chassis.__str__())
        self.vswitch_api.add_tunnel_port(chassis).execute()

    def chassis_deleted(self, chassis_id):
        LOG.info(_LI("Deleting tunnel to remote chassis = %s") % chassis_id)
        tunnel_ports = self.vswitch_api.get_tunnel_ports()
        for port in tunnel_ports:
            if port.get_chassis_id() == chassis_id:
                self.vswitch_api.delete_port(port).execute()
                return

    def _vm_port_online(self, ovs_port):

        port_id = ovs_port['type']
        lport = self._get_lport(port_id)
        assert lport is not None, "Port:{id} not found".format(id=port_id)

        switch_id = lport.get_lswitch_id()
        tenant_id = lport.get_tenant_id()
        lswitch = self._get_lswitch(switch_id, tenant_id)
        assert lswitch is not None, "Switch for port:{id} not found".format(
                id=port_id)

        subnets = lswitch.get_subnets()
        # Todo, use subnet that port's ip belongs to
        self._get_lrouter_by_subnet(subnets[0], tenant_id)

        self._add_to_topic_subscribed(tenant_id, lport.get_id())
        self._publish_vm_port_online(lport)

    def _tunnel_port_online(self):
        pass

    def _patch_port_online(self):
        pass

    def _vm_port_offline(self, ovs_port):
        port_id = ovs_port['type']
        lport = self._get_lport(port_id)
        assert lport is not None, "Port:{id} not found".format(id=port_id)

        tenant_id = lport.get_tenant_id()

        self._del_from_topic_subscribed(tenant_id, lport.get_id())
        self._publish_vm_port_offline(lport)

    def _tunnel_port_offline(self):
        pass

    def _patch_port_offline(self):
        pass

    def _add_to_topic_subscribed(self, topic, element):

        if topic not in self.topic_subscribed:
            self.nb_api.subscribe(topic)
            self.topic_subscribed[topic] = [element]

    def _del_from_topic_subscribed(self, topic, element):

        elements = self.topic_subscribed[topic]
        elements = elements.remove[element]
        if len(elements) == 0:
            self.topic_subscribed.pop(topic)
            self.nb_api.unsubscribe(topic)
        else:
            self.topic_subscribed[topic] = elements

    def _publish_vm_port_online(self, lport):
        LOG.info(_LI("Vm port(%s) online") % lport)
        self.openflow_app.notify_vm_port_online(lport)

    def _publish_vm_port_offline(self, lport):
        LOG.info(_LI("Vm port(%s) offline") % lport)
        self.openflow_app.notify_vm_port_offline(lport)

    def _add_new_lrouter_port(self, router, router_port):
        LOG.info(_LI("Adding new logical router interface = %s") %
                 router_port.__str__())
        local_network_id = self._get_network_id(
                router_port.get_lswitch_id())
        self.openflow_app.notify_add_router_port(
                router, router_port, local_network_id)

    def _delete_lrouter_port(self, router_port):
        LOG.info(_LI("Removing logical router interface = %s") %
                 router_port.__str__())
        local_network_id = self._get_network_id(
                router_port.get_lswitch_id())
        self.openflow_app.notify_remove_router_port(
                router_port, local_network_id)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_lrouter_port(lrouter, new_port)
        self.db_store.update_router(lrouter.get_id(), lrouter)

    def _update_lrouter_ports(self, old_router, new_router):
        new_router_ports = new_router.get_ports()
        old_router_ports = old_router.get_ports()
        for new_port in new_router_ports:
            if new_port not in old_router_ports:
                self._add_new_lrouter_port(new_router, new_port)
            else:
                old_router_ports.remove(new_port)

        for old_port in old_router_ports:
            self._delete_lrouter_port(old_port)

    def _get_lport(self, port_id, tenant_id=None):

        lport = self.db_store.get_port(port_id)

        if lport is None:
            lport = self.nb_api.get_logical_port(port_id, tenant_id)

            if lport is not None:
                self.db_store.set_port(port_id, lport)

        return lport

    def _get_lswitch(self, switch_id, tenant_id=None):
        lswitch = self.db_store.get_lswitch(switch_id)

        if lswitch is None:
            lswitch = self.nb_api.get_lswitch(switch_id, tenant_id)

            if lswitch is not None:
                self.db_store.set_lswitch(switch_id, lswitch)
                self._cache_lswitch(lswitch)

        return lswitch

    def _get_lrouter_by_subnet(self, subnet_id, tenant_id):
        routers = self.nb_api.get_all_lrouters(tenant_id)
        for router in routers:
            subnets = router.get_subnets()
            if subnet_id in subnets:
                self._cache_lrouter(router, tenant_id)
                return router
        return None

    def _cache_lswitch(self, lswitch):
        tenant_id = lswitch.get_tenant_id()
        switch_id = lswitch.get_id()
        tenant_ports = self.nb_api.get_all_logical_ports(tenant_id)

        for port in tenant_ports:
            if switch_id == port.get_lswitch_id():
                self.db_store.set_port(port.get_port_id, port)

    def _cache_lrouter(self, lrouter, tenant_id):
        subnets = lrouter.get_subnets()
        for subnet in subnets:
            switch_id = subnet.get_switch_id
            self._get_lswitch(switch_id)

    def _get_network_id(self, logical_dp_id):
        network_id = self.db_store.get_network_id(logical_dp_id)
        if network_id is not None:
            return network_id
        else:
            self.next_network_id += 1
            # TODO(gsagie) verify self.next_network_id didnt wrap
            self.db_store.set_network_id(logical_dp_id, self.next_network_id)
            return self.next_network_id
