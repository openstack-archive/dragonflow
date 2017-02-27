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

import uuid

from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.services.trunk import constants
from neutron.services.trunk.drivers import base

from dragonflow import conf as cfg
from dragonflow.db.models import trunk as trunk_models


class DragonflowDriver(base.DriverBase):
    def is_loaded(self):
        try:
            # TODO(oanson) 'df' -> constant
            return 'df' in cfg.CONF.ml2.mechanism_drivers
        except cfg.NoSuchOptError:
            return False

    def register(self, resource, event, trigger, **kwargs):
        """Register the Dragonflow driver. This means registering to the
        add subport and delete subport events
        """
        super(DragonflowDriver, self).register(resource, event, trigger,
                                               **kwargs)
        registry.subscribe(self._add_subports_handler,
                           constants.SUBPORTS, events.AFTER_CREATE)
        registry.subscribe(self._delete_subports_handler,
                           constants.SUBPORTS, events.AFTER_DELETE)

    def _get_subport_id(self, trunk, subport):
        """Generate a repeatable uuid, so we can identify the Dragonflow
        ChildPortSegmentation object
        """
        base = "{}/{}".format(subport.trunk.port_id, subport.port_id)
        return uuid.uuid5(trunk.UUID_NAMESPACE, base)

    def _add_subports_handler(self, *args, **kwargs):
        """Handle the event that subports were created"""
        payload = kwargs['payload']
        trunk = payload.current_trunk
        subports = payload.subports
        self._add_subports(trunk, subports)

    def _add_subports(self, trunk, subports):
        """Create the subports that were created on the Neutron side in the
        Dragonflow NB DB
        """
        for subport in subports:
            self._add_subport(subport)

    def _add_subport(self, trunk, subport):
        """Create the subport that were created on the Neutron side in the
        Dragonflow NB DB
        """
        model = trunk_models.ChildPortSegmentation(
            id=self._get_subport_id(trunk, subport),
            topic=trunk.project_id,
            parent=subport.trunk_id,
            port=subport.port_id,
            segmentation_type=subport.segmentation_type,
            segmentation_id=subport.segmentation_id,
        )
        self.nb_api.create(model)

    def _delete_subports_handler(self, *args, **kwargs):
        """Handle the event that subports were created"""
        payload = kwargs['payload']
        trunk = payload.current_trunk
        subports = payload.subports
        self._delete_subports(trunk, subports)

    def _delete_subports(self, trunk, subports):
        """Remove the subports that were deleted on the Neutron side from the
        Dragonflow NB DB
        """
        for subport in subports:
            self._delete_subport(trunk, subport)

    def _delete_subport(self, trunk, subport):
        """Remove the subport that were deleted on the Neutron side from the
        Dragonflow NB DB
        """
        id_ = self._get_subport_id(trunk, subport)
        model = trunk_models.ChildPortSegmentation(
            id=id_,
            topic=trunk.project_id
        )
        self.nb_api.delete(model)
