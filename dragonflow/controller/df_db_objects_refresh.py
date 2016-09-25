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

import six


class DfObjectRefresher(object):
    """Handles all the lifecycle of object refresh from the DB.

    This is done using callback methods for each object type.
    """

    def __init__(self,
                 obj_type,
                 db_read_callback,
                 read_callback,
                 update_callback,
                 delete_callback):
        """Initializes all the callbacks that should be used."""
        self.obj_type = obj_type
        self.db_read_callback = db_read_callback
        self.read_callback = read_callback
        self.update_callback = update_callback
        self.delete_callback = delete_callback
        self.objects_to_remove = {}

    def read(self):
        """Reads the objects from the database."""
        for curr_obj in self.db_read_callback():
            self.objects_to_remove[curr_obj.get_id()] = curr_obj

    def update(self):
        """Updates existing objects and marks obsolete ones for removal.

        This is done by reading all the current objects from the repository
        and comparing it with the list we got from the database.
        For every object that exists in both, we update it, and for each
        object that was removed from the DB we mark it for removal.
        """
        for my_object in self.read_callback():
            self.update_callback(my_object)
            obj_id = my_object.get_id()
            self.objects_to_remove.pop(obj_id, None)

    def delete(self):
        """Does the actual removal of the objects marked for removal.

        The marking is done using the update method, and the removal
        is done by using the relevant callback.
        """
        if self.objects_to_remove:
            for _id, curr_obj in six.iteritems(self.objects_to_remove):
                self.delete_callback(curr_obj)
