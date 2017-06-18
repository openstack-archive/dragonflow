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

from jsonmodels import fields
from jsonmodels import models
from neutron_lib.api.definitions import portbindings
from neutron_lib import constants as n_const
from oslo_log import log

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import core
from dragonflow.db.models import host_route
from dragonflow.db.models import mixins
from dragonflow.db.models import qos
from dragonflow.db.models import secgroups

LOG = log.getLogger(__name__)


@mf.construct_nb_db_model
class Subnet(mf.ModelBase, mixins.Name, mixins.Topic):
    enable_dhcp = fields.BoolField()
    dhcp_ip = df_fields.IpAddressField()
    cidr = df_fields.IpNetworkField()
    gateway_ip = df_fields.IpAddressField()
    dns_nameservers = df_fields.ListOfField(df_fields.IpAddressField())
    host_routes = fields.ListField(host_route.HostRoute)


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'network_type': 'network_type',
        'physical_network': 'physical_network',
    },
)
class LogicalSwitch(mf.ModelBase, mixins.Name, mixins.Version, mixins.Topic,
                    mixins.UniqueKey, mixins.BasicEvents):

    table_name = "lswitch"

    is_external = fields.BoolField()
    mtu = fields.IntField()
    subnets = fields.ListField(Subnet)
    segmentation_id = fields.IntField()
    # TODO(oanson) Validate network_type
    network_type = fields.StringField()
    # TODO(oanson) Validate physical_network
    physical_network = fields.StringField()
    qos_policy = df_fields.ReferenceField(qos.QosPolicy)

    def find_subnet(self, subnet_id):
        for subnet in self.subnets:
            if subnet.id == subnet_id:
                return subnet

    def add_subnet(self, subnet):
        self.subnets.append(subnet)

    def remove_subnet(self, subnet_id):
        for idx, subnet in enumerate(self.subnets):
            if subnet.id == subnet_id:
                return self.subnets.pop(idx)


class AddressPair(models.Base):
    ip_address = df_fields.IpAddressField(required=True)
    mac_address = df_fields.MacAddressField(required=True)


class DHCPOption(models.Base):
    tag = fields.IntField(required=True)
    value = fields.StringField(required=True)


# LogicalPort events
EVENT_LOCAL_CREATED = 'local_created'
EVENT_REMOTE_CREATED = 'remote_created'
EVENT_VIRTUAL_CREATED = 'virtual_created'
EVENT_LOCAL_UPDATED = 'local_updated'
EVENT_REMOTE_UPDATED = 'remote_updated'
EVENT_VIRTUAL_UPDATED = 'virtual_updated'
EVENT_LOCAL_DELETED = 'local_deleted'
EVENT_REMOTE_DELETED = 'remote_deleted'
EVENT_VIRTUAL_DELETED = 'virtual_deleted'


@mf.register_model
@mf.construct_nb_db_model(events={
    EVENT_LOCAL_CREATED, EVENT_REMOTE_CREATED, EVENT_VIRTUAL_CREATED,
    EVENT_LOCAL_UPDATED, EVENT_REMOTE_UPDATED, EVENT_VIRTUAL_UPDATED,
    EVENT_LOCAL_DELETED, EVENT_REMOTE_DELETED, EVENT_VIRTUAL_DELETED,
}, indexes={
    'chassis_id': 'chassis.id',
    'lswitch_id': 'lswitch.id',
    'ip,lswitch': ('ips', 'lswitch.id'),
})
class LogicalPort(mf.ModelBase, mixins.Name, mixins.Version, mixins.Topic,
                  mixins.UniqueKey):
    table_name = "lport"
    ips = df_fields.ListOfField(df_fields.IpAddressField())
    subnets = df_fields.ReferenceListField(Subnet)
    macs = df_fields.ListOfField(df_fields.MacAddressField())
    enabled = fields.BoolField()
    chassis = df_fields.ReferenceField(core.Chassis)
    lswitch = df_fields.ReferenceField(LogicalSwitch)
    security_groups = df_fields.ReferenceListField(secgroups.SecurityGroup)
    allowed_address_pairs = fields.ListField(AddressPair)
    port_security_enabled = fields.BoolField()
    device_owner = fields.StringField()
    device_id = fields.StringField()
    qos_policy = df_fields.ReferenceField(qos.QosPolicy)
    remote_vtep = fields.BoolField()
    extra_dhcp_options = df_fields.IntStringDictField()
    binding_vnic_type = df_fields.EnumField(portbindings.VNIC_TYPES)

    def __init__(self, ofport=None, is_local=None,
                 peer_vtep_address=None, **kwargs):
        super(LogicalPort, self).__init__(**kwargs)
        self.ofport = ofport
        self.is_local = is_local
        self.peer_vtep_address = peer_vtep_address

    @property
    def ip(self):
        try:
            return self.ips[0]
        except IndexError:
            return None

    @property
    def mac(self):
        try:
            return self.macs[0]
        except IndexError:
            return None

    def is_vm_port(self):
        """
        Return True if the device owner starts with 'compute:' (or is None)
        """
        owner = self.device_owner
        if not owner or owner.startswith(n_const.DEVICE_OWNER_COMPUTE_PREFIX):
            return True
        return False

    @property
    def is_virtual(self):
        return self.chassis is None

    @property
    def is_remote(self):
        return not self.is_local and self.chassis is not None

    def __str__(self):
        data = {}
        for name in dir(self):
            if name.startswith('_'):
                continue
            cls_definition = getattr(self.__class__, name, None)
            if isinstance(cls_definition, fields.BaseField):
                if name in self._set_fields:
                    data[name] = getattr(self, name)
            elif not cls_definition:  # Display only instnaces, not classes
                data[name] = getattr(self, name)
        return str(data)

    def emit_created(self):
        if not self.is_virtual and self.ofport is None:
            return

        LOG.info("Adding new logical port = %s", self)
        if self.is_local:
            self.emit_local_created()
        elif self.is_remote:
            self.emit_remote_created()
        elif self.is_virtual:
            self.emit_virtual_created()

    def emit_updated(self, original_lport):
        if not self.is_virtual and self.ofport is None:
            return

        LOG.info("Updating %(location)s logical port = %(port)s, "
                 "original port = %(original_port)s",
                 {'port': self,
                  'original_port': original_lport,
                  'location': 'local' if self.is_local else 'remote'})
        if self.is_local:
            self.emit_local_updated(original_lport)
        elif self.is_remote:
            self.emit_remote_updated(original_lport)
        elif self.is_virtual:
            self.emit_virtual_updated(original_lport)

    def emit_deleted(self):
        if not self.is_virtual and self.ofport is None:
            return

        if self.is_local:
            self.emit_local_deleted()
        elif self.is_remote:
            self.emit_remote_deleted()
        elif self.is_virtual:
            self.emit_virtual_deleted()
