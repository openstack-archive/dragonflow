# Copyright (c) 2016 OpenStack Foundation.
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


class DfObjectRefresher(object):
    """Handles all the lifecycle of object refresh from the DB.

    This is done using callback methods for each object type.
    """

    def __init__(self,
                 obj_type,
                 cache_read_ids_callback,
                 db_read_objects_callback,
                 cache_update_object_callback,
                 cache_delete_id_callback):
        """Initializes all the callback methods that should be used."""
        self.obj_type = obj_type
        self.cache_read_ids_callback = cache_read_ids_callback
        self.db_read_objects_callback = db_read_objects_callback
        self.cache_update_object_callback = cache_update_object_callback
        self.cache_delete_id_callback = cache_delete_id_callback
        self.object_ids_to_remove = set()

    def read(self, topic=None):
        """Reads the objects IDs from the cache."""
        self.object_ids_to_remove = set(self.cache_read_ids_callback(topic))

    def update(self, topic=None):
        """Updates existing objects and marks obsolete ones for removal.

        This is done by reading all the current objects from the database
        and comparing it with the list we got from the cache.
        For every object that exists in both, we update it, and for each
        object that was removed from the DB we mark it for removal.
        """
        for obj in self.db_read_objects_callback(topic):
            self.cache_update_object_callback(obj)
            obj_id = obj.get_id()
            self.object_ids_to_remove.discard(obj_id)

    def delete(self):
        """Does the actual removal of the objects marked for removal.

        The marking is done using the update method, and the removal
        is done by using the relevant callback.
        """
        for curr_id in self.object_ids_to_remove:
            self.cache_delete_id_callback(curr_id)
        self.object_ids_to_remove.clear()


# List of DfObjectRefresher.
items = []


def initialize_object_refreshers(df_controller):
    db_store = df_controller.get_db_store()
    nb_api = df_controller.get_nb_api()

    items.append(DfObjectRefresher('QoS Policies',
                                   db_store.get_qos_policy_keys,
                                   nb_api.get_qos_policies,
                                   df_controller.update_qospolicy,
                                   df_controller.delete_qospolicy))
    items.append(DfObjectRefresher('Switches',
                                   db_store.get_lswitch_keys,
                                   nb_api.get_all_logical_switches,
                                   df_controller.update_lswitch,
                                   df_controller.delete_lswitch))
    items.append(DfObjectRefresher('Security Groups',
                                   db_store.get_security_group_keys,
                                   nb_api.get_security_groups,
                                   df_controller.update_secgroup,
                                   df_controller.delete_secgroup))
    items.append(DfObjectRefresher('Ports',
                                   db_store.get_port_keys,
                                   nb_api.get_all_logical_ports,
                                   df_controller.update_lport,
                                   df_controller.delete_lport))
    items.append(DfObjectRefresher('Routers',
                                   db_store.get_router_keys,
                                   nb_api.get_routers,
                                   df_controller.update_lrouter,
                                   df_controller.delete_lrouter))
    items.append(DfObjectRefresher('Floating IPs',
                                   db_store.get_floatingip_keys,
                                   nb_api.get_floatingips,
                                   df_controller.update_floatingip,
                                   df_controller.delete_floatingip))
    items.append(DfObjectRefresher('Active Ports',
                                   db_store.get_active_port_keys,
                                   nb_api.get_active_ports,
                                   df_controller.update_activeport,
                                   df_controller.delete_activeport))


def sync_local_cache_from_nb_db(topics=None):
    """Sync local db store from nb db and apply to local OpenFlow

    @param topics: The topics that the sync will be performed. If empty or
                   None, all topics will be synced.
    @return : None
    """
    def _refresh_items(topic=None):
        # Refresh all the objects and find which ones should be removed
        for item in items:
            item.read(topic)
            item.update(topic)

        # Remove obsolete objects in reverse order
        for item in reversed(items):
            item.delete()

    if topics is None:
        _refresh_items()
    else:
        for topic in topics:
            _refresh_items(topic)


def clear_local_cache(topics=None):
    """Clear local db store and clear local OpenFlow

    @param topics: The topics that the clear will be performed. If empty or
                   None, all topics will be cleared.
    @return : None
    """
    def _delete_items(topic=None):
        for item in reversed(items):
            item.read(topic)
            item.delete()

    if topics is None:
        _delete_items()
    else:
        for topic in topics:
            _delete_items(topic)


def process_object(controller, table, action, argument):
    if action == 'delete':
        method_name = 'delete_' + table
    else:
        method_name = 'update_' + table
    handler = getattr(controller, method_name, None)
    if handler:
        handler(argument)
