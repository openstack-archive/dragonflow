import mock

from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_store
from dragonflow.ovsdb import vswitch_impl as vswitch_api
from dragonflow.tests import base as test_base


class DfLocalControllerTestCase(test_base.BaseTestCase):

    controller = df_local_controller.DfLocalController('foobar')

    def _get_mock_chassis(self, ids):
        all_chassis = []
        for i in ids:
            mock_chassis = mock.Mock()
            mock_chassis.get_id = mock.Mock()
            mock_chassis.get_id.return_value = i
            all_chassis.append(mock_chassis)
        return all_chassis

    def _get_mock_ports(self, chassis_ids):
        ports = []
        for chassis_id in chassis_ids:
            mock_port = mock.Mock()
            mock_port.get_chassis_id = mock.Mock()
            mock_port.get_chassis_id.return_value = chassis_id
            ports.append(mock_port)
        return ports

    @mock.patch.object(vswitch_api.OvsApi , 'delete_port')
    @mock.patch.object(vswitch_api.OvsApi ,'get_tunnel_ports')
    def test_chassis_deleted(self, mock_get, mock_delete):
        # Creating a list of ports to be returned for get_tunnel_ports
        # Creating the get_chassis_id calls for the ports
        chassis_id = '1234'
        not_chassis_id = '5678'
        ids = [chassis_id, not_chassis_id]
        
        mock_get.return_value = self._get_mock_ports(ids)
        # Testing the function
        self.controller.chassis_deleted(ids[0])
        mock_delete.assert_called_once_with(mock_get.return_value[0])

    @mock.patch.object(vswitch_api.OvsApi, 'add_tunnel_port')
    @mock.patch.object(vswitch_api.OvsApi, 'get_tunnel_ports')
    def test_chassis_created(self, mock_get_ports, mock_add):
        # test self.chassis_name == chassis.get_id()
        mock_chassis = mock.Mock()
        mock_chassis.get_id = mock.Mock()
        mock_chassis.get_id.return_value = self.controller.chassis_name
        self.assertIsNone(self.controller.chassis_created(mock_chassis))
        # test t_port.get_chassis_id() == chassis.get_id()
        port_id = 'fake_port_id'
        ids = [port_id]
        mock_chassis.get_id.return_value = port_id
        mock_get_ports.return_value = self._get_mock_ports(ids)
        self.assertIsNone(self.controller.chassis_created(mock_chassis))
        # normal execution
        ids = ['not %s' % self.controller.chassis_name]
        mock_get_ports.return_value = self._get_mock_ports(ids)
        self.controller.chassis_created(mock_chassis)
        mock_add.assert_called_once_with(mock_chassis)

    @mock.patch.object(df_local_controller.DfLocalController,
                       'chassis_created')
    @mock.patch.object(api_nb.NbApi, 'get_all_chassis')
    @mock.patch.object(vswitch_api.OvsApi, 'delete_port')
    @mock.patch.object(vswitch_api.OvsApi, 'get_tunnel_ports')
    def test_create_tunnels(self, mock_get_ports, mock_delete, mock_get_all,
                            mock_create):
        shared_chassis = 'matching_chassis'
        port_ids = [shared_chassis, 'to be deleted']
        # Each item in the following list tests each branch of the if elif else
        # in the for loop respectively
        chassis_ids = [shared_chassis, self.controller.chassis_name, 'else']
        mock_get_ports.return_value = self._get_mock_ports(port_ids)
        mock_get_all.return_value = self._get_mock_chassis(chassis_ids)
        self.controller.create_tunnels()
        mock_create.assert_called_once_with(mock_get_all.return_value[2])
        # tests iterate all tunnel ports that needs to be deleted
        mock_delete.assert_called_once_with(mock_get_ports.return_value[1])

    def _get_mock_secgroup(self, rules, secgroup_id):
        secgroup = mock.Mock()
        secgroup.get_rules = mock.Mock()
        secgroup.get_rules.return_value = rules
        secgroup.get_id = mock.Mock()
        secgroup.get_id.return_value = secgroup_id
        return secgroup

    @mock.patch.object(db_store.DbStore, 'update_security_group')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_add_new_security_group_rule')
    def test__add_new_security_group(self, mock_add, mock_update):
        rules = ['new_rule']
        secgroup_id = 'fake id'
        mock_secgroup = self._get_mock_secgroup(rules, secgroup_id)
        self.controller._add_new_security_group(mock_secgroup)
        mock_add.assert_called_once_with(mock_secgroup, rules[0])
        mock_update.assert_called_once_with(secgroup_id, mock_secgroup)

    @mock.patch.object(db_store.DbStore, 'delete_security_group')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_delete_security_group_rule')
    def test__delete_old_security_group(self, mock_delete, mock_db_delete):
        rules = ['old_rule']
        secgroup_id = 'fake_id'
        mock_secgroup = self._get_mock_secgroup(rules, secgroup_id)
        self.controller._delete_old_security_group(mock_secgroup)
        mock_delete.assert_called_once_with(mock_secgroup, rules[0])
        mock_db_delete.assert_called_once_with(secgroup_id)

    
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_delete_security_group_rule')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_add_new_security_group_rule')
    def test__update_security_group_rules(self, mock_add, mock_delete):
        shared_rule = 'to_be_removed'
        secgroup_id = 'fake_id'
        old_rules = [shared_rule, 'old_rule']
        new_rules = [shared_rule, 'new_rule']
        new_secgroup = self._get_mock_secgroup(new_rules,
                                               'new_%s' % secgroup_id)
        old_secgroup = self._get_mock_secgroup(old_rules,
                                               'old_%s' % secgroup_id)
        self.controller._update_security_group_rules(old_secgroup,
                                                     new_secgroup)
        mock_add.assert_called_once_with(new_secgroup, new_rules[1])

        def _check_removed_index():
            old_rules[1]

        self.assertRaises(IndexError, _check_removed_index)
        mock_delete.assert_called_once_with(old_secgroup, 'old_rule')

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 
                       'notify_add_security_group_rule')
    def test__add_new_security_group_rule(self, mock_app_notify):
        secgroup = mock.Mock()
        secgroup_rule = mock.Mock()
        self.controller._add_new_security_group_rule(secgroup, secgroup_rule)
        mock_app_notify.assert_called_once_with(secgroup, secgroup_rule)

    
    @mock.patch.object(ryu_base_app.RyuDFAdapter, 
                       'notify_remove_security_group_rule')
    def test__delete_security_group_rule(self, mock_app_notify):
        secgroup = mock.Mock()
        secgroup_rule = mock.Mock()
        self.controller._delete_security_group_rule(secgroup, secgroup_rule)
        mock_app_notify.assert_called_once_with(secgroup, secgroup_rule)

    def _get_mock_floatingip(self, lport_id, fip_id):
        floatingip = mock.Mock()
        floatingip.get_lport_id = mock.Mock()
        floatingip.get_lport_id.return_value = lport_id
        floatingip.get_id = mock.Mock()
        floatingip.get_id.return_value = fip_id
        return floatingip


    @mock.patch.object(df_local_controller.DfLocalController,
                       '_update_floatingip')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_is_valid_version')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_associate_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_local_port')
    def test_floatingip_updated(self, mock_get_lport, mock_get_fip,
                                mock_assoc, mock_is_valid, mock_update):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        mock_get_lport.return_value = None
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_get_lport.assert_called_once_with(lport_id)

        mock_get_fip.return_value = None
        fip.get_lport_id.return_value = None
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_get_fip.assert_called_once_with(fip_id)

        mock_get_lport.return_value = mock.Mock()
        fip.get_lport_id.return_value = lport_id
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_assoc.assert_called_once_with(fip)

        old_fip = mock.Mock()
        mock_get_fip.return_value = old_fip
        mock_is_valid.return_value = False
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_is_valid.assert_called_once()

        mock_is_valid.return_value = True
        self.controller.floatingip_updated(fip)
        mock_update.assert_called_once_with(old_fip, fip)
        

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_delete_floatingip') 
    @mock.patch.object(db_store.DbStore, 'get_floatingip')
    def test_floatingip_deleted(self, mock_get_fip, mock_notify):
        mock_get_fip.return_value = None
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.assertIsNone(self.controller.floatingip_deleted(fip_id))
        mock_get_fip.return_value = fip 
        self.controller.floatingip_deleted(fip_id)
        mock_notify.assert_called_once_with(fip)

    #def _get_mock_publisher(self, uri, publisher_id):
    #    publisher = mock.Mock()
    #    publisher.get_uri = mock.Mock()
    #    publisher.get_uri.return_value = uri
    #    publisher.get_id = mock.Mock()
    #    publisher.get_id.return_value = publisher_id
    #    return publisher

    #@mock.patch.object(zmq_pubsub_driver.ZMQSubscriberAgentBase,'register_listen_address')
    #@mock.patch.object(db_store.DbStore, 'update_publisher')
    #def test_publisher_updated(self, mock_update, mock_subscriber):
    #    uri = 'fake_uri'
    #    publisher_id = 'fake_publisher_id'
    #    publisher = self._get_mock_publisher(uri, publisher_id)
    #    self.controller.publisher_updated(publisher)
    #    mock_update.assert_called_once_with(publisher_id, publisher)
    
    #def test_publisher_deleted(self):
    #    pass

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_associate_floatingip')
    @mock.patch.object(db_store.DbStore, 'update_floatingip')
    def test__associate_floatingip(self, mock_update, mock_notify):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.controller._associate_floatingip(fip)
        mock_update.assert_called_once_with(fip_id, fip)
        mock_notify.assert_called_once_with(fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_disassociate_floatingip')
    @mock.patch.object(db_store.DbStore, 'delete_floatingip')
    def test__disassociate_floatingip(self, mock_delete, mock_notify):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.controller._disassociate_floatingip(fip)
        mock_delete.assert_called_once_with(fip_id)
        mock_notify.assert_called_once_with(fip)

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_associate_floatingip')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_disassociate_floatingip')
    def test__update_floatingip(self, mock_disassoc, mock_assoc):
        old_lport_id = 'fake_old_lport_id'
        old_fip_id = 'fake_old_fip_id'
        old_fip = self._get_mock_floatingip(old_lport_id, old_fip_id)
        new_lport_id = 'fake_new_lport_id'
        new_fip_id = 'fake_new_fip_id'
        new_fip = self._get_mock_floatingip(new_lport_id, new_fip_id)
        self.controller._update_floatingip(old_fip, new_fip)
        mock_disassoc.called_once_with(old_fip)
        mock_assoc.called_once_with(new_fip)

    #@mock.patch.object(topology.Topology, 'ovs_port_deleted')
    #@mock.patch.object(ryu_base_app.RyuDFAdapter,
    #                   'notify_ovs_port_deleted')
    #def test_ovs_port_deleted(self, mock_notify, mock_delete):
    #    ovs_port = self._get_mock_ports('fake_port_id')[0]
    #    self.controller.ovs_port_deleted(ovs_port)
    #    mock_notify.assert_called_once_with(ovs_port)
    #    mock_delete.assert_called_once_with(ovs_port)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_ovs_sync_finished')
    def test_ovs_sync_finished(self, mock_notify):
        self.controller.ovs_sync_finished()
        mock_notify.assert_called_once()

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_ovs_sync_started')
    def test_ovs_sync_finished(self, mock_notify):
        self.controller.ovs_sync_started()
        mock_notify.assert_called_once()
