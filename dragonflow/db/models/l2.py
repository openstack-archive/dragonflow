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
import netaddr
from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.db import db_store2
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import core
from dragonflow.db.models import host_route
from dragonflow.db.models import mixins
from dragonflow.db.models import qos
from dragonflow.db.models import secgroups

LOG = log.getLogger(__name__)


@mf.construct_nb_db_model
class Subnet(mf.ModelBase, mixins.Topic):
    enable_dhcp = fields.BoolField()
    dhcp_ip = df_fields.IpAddressField()
    cidr = df_fields.IpNetworkField()
    gateway_ip = df_fields.IpAddressField()
    dns_nameservers = fields.ListField(netaddr.IPAddress)
    host_routes = fields.ListField(host_route.HostRoute)


@mf.register_model
@mf.construct_nb_db_model(indexes={'network_type': 'network_type'})
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


@mf.construct_nb_db_model
class AddressPair(mf.ModelBase):
    id = None
    ip_address = df_fields.IpAddressField(required=True)
    mac_address = df_fields.MacAddressField(required=True)


@mf.construct_nb_db_model
class DHCPOption(mf.ModelBase):
    id = None
    name = fields.StringField(required=True)
    value = fields.StringField(required=True)


# LogicalPort events
EVENT_LOCAL_CREATED = 'LOCAL_CREATED'
EVENT_REMOTE_CREATED = 'REMOTE_CREATED'
EVENT_LOCAL_UPDATED = 'LOCAL_UPDATED'
EVENT_REMOTE_UPDATED = 'REMOTE_UPDATED'
EVENT_LOCAL_DELETED = 'LOCAL_DELETED'
EVENT_REMOTE_DELETED = 'REMOTE_DELETED'


@mf.register_model
@mf.construct_nb_db_model(events={
    EVENT_LOCAL_CREATED, EVENT_REMOTE_CREATED,
    EVENT_LOCAL_UPDATED, EVENT_REMOTE_UPDATED,
    EVENT_LOCAL_DELETED, EVENT_REMOTE_DELETED,
}, indexes={
    'chassis_id': 'chassis.id',
    'lswitch_id': 'lswitch.id',
})
class LogicalPort(mf.ModelBase, mixins.Name, mixins.Version, mixins.Topic,
                  mixins.UniqueKey):
    table = "lport"
    ips = fields.ListField(netaddr.IPAddress)
    subnets = df_fields.ReferenceListField(Subnet)
    macs = fields.ListField(netaddr.EUI)
    chassis = df_fields.ReferenceField(core.Chassis)
    lswitch = df_fields.ReferenceField(LogicalSwitch)
    security_groups = df_fields.ReferenceListField(secgroups.SecurityGroup)
    allowed_address_pairs = fields.ListField(AddressPair)
    port_security_enabled = fields.BoolField()
    device_owner = fields.StringField()
    device_id = fields.StringField()
    qos_policy = df_fields.ReferenceField(qos.QosPolicy)
    remote_vtep = fields.BoolField()
    extra_dhcp_options = fields.ListField(DHCPOption)

    @property
    def ip(self):
        try:
            return self.ips[0]
        except IndexError:
            return None

    def __str__(self):
        data = {}
        for name in dir(self):
            cls_definition = getattr(self.__class__, name)
            if isinstance(cls_definition, fields.BaseField):
                if name in self._set_fields:
                    data[name] = getattr(self, name)
            elif not name.startswith('_'):
                data[name] = getattr(self, name)
        return str(data)

    def emit_updated(self):
        ofport = getattr(self, 'ofport', None)
        if not ofport:
            return
        is_local = getattr(self, 'is_local', None)
        db_store_inst = db_store2.get_instance()
        original_lport = db_store_inst.get_one(self)
        if original_lport is None:
            LOG.info(_LI("Adding new logical port = %s"), self)
            if is_local:
                self.emit_local_created()
            else:
                self.emit_remote_created()
        else:
            LOG.info(_LI("Updating %(location)s logical port = %(port)s, "
                         "original port = %(original_port)s"),
                     {'port': self,
                      'original_port': original_lport,
                      'location': 'local' if is_local else 'remote'})
            if is_local:
                self.emit_local_updated(original_lport)
            else:
                self.emit_remote_updated(original_lport)

    def emit_deleted(self):
        is_local = getattr(self, 'is_local', None)
        ofport = getattr(self, 'ofport', None)
        if not ofport:
            return
        if is_local:
            self.emit_local_deleted()
        else:
            self.emit_remote_deleted()
