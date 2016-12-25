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
# import netaddr

from dragonflow.db import crud
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
# from dragonflow.db import model_proxy
from dragonflow.utils import namespace


def _normalize(obj):
    '''Receives an object or a sequence, if we got an object, wrap it in a
       tuple of one and return it, otherwise return the sequence

       >>> _normalize(1)
       (1, )
       >>> _normalize([1, 2])
       (1, 2)
    '''
    try:
        if isinstance(obj, str):
            return (obj,)
        return tuple(obj)
    except TypeError:
        return (obj,)


# O(a lot) db store implementation
class MockDbStore(object):
    def __init__(self):
        self._store = {}

    def _extract_key(self, obj, index):
        return tuple(getattr(obj, field) for field in index)

    def get(self, model, index, key):
        index = _normalize(index)
        key = _normalize(key)

        for obj in self._store.get(model, ()):
            if self._extract_key(obj, index) == key:
                return obj

        raise KeyError(key)

    def store(self, obj):
        self._store.setdefault(type(obj), []).append(obj)


db_store = MockDbStore()


@mf.construct_nb_db_model(
    indexes=namespace.Namespace(
        id='id',
        id_topic=('id', 'topic'),
    ),
    events=('created', 'updated', 'deleted'),
    nb_crud=crud.NbApiCRUD,
)
class NbModelBase(mf.ModelBase):
    id = fields.StringField(required=True)
    topic = fields.StringField()

    def is_stale(self):
        return False


@mf.construct_nb_db_model
class NbDbModelBase(NbModelBase):
    name = fields.StringField()
    version = fields.IntField()


class NbDbUniqueKeyMixin(mf.ModelBase):
    unique_key = fields.IntField(required=True)


@mf.register_model
@mf.construct_nb_db_model
class Chassis(NbDbModelBase):
    table_name = 'chassis'

    ip = df_fields.IpAddressField(required=True)
    tunnel_type = df_fields.EnumField(('vxlan', 'gre', 'geneve'),
                                      required=True)


# @mf.register_model
# @mf.construct_nb_db_model
# class Subnet(NbModelBase):
#     name = fields.StringField()
#     cidr = df_fields.IpNetworkField(required=True)
#     enable_dhcp = fields.BoolField(required=True)
#     dhcp_server_address = fields.StringField()
#     gateway_ip = df_fields.IpAddressField()
#     dns_servers = fields.ListField(netaddr.IPAddress)
#     host_routes = fields.ListField(str)


# @mf.register_model
# @mf.construct_nb_db_model
# class LogicalSwitch(NbDbUniqueKeyMixin, NbDbModelBase):
#     subnets = fields.ListField(Subnet)
#     mtu = fields.IntField()
#     external = fields.BoolField()
#     segment_id = fields.IntField()
#     network_type = fields.StringField()
#     physical_network = fields.StringField()


# @mf.register_model
# @mf.construct_nb_db_model
# class LogicalPort(NbDbModelBase):
#     ip_list = fields.ListField(netaddr.IPAddress)
#     macs = fields.ListField(str)
#     subnets = fields.ListField(model_proxy.create_model_proxy(Subnet)),
#     chassis = df_fields.ReferenceField(Chassis)
#     lswitch = df_fields.ReferenceField(LogicalSwitch)
#     security_groups = fields.ListField(
#         model_proxy.create_model_proxy('SecurityGroup'))
#     allowed_address_pairs = fields.ListField('AddressPair')
#     port_security_enabled = fields.BoolField()
#     device_owner = fields.StringField()
#     device_id = fields.StringField()
#     binding_profile = fields.StringField()
#     binding_vnic_type = fields.StringField()
#     qos_policy = df_fields.ReferenceField('QosPolicy')
#     remote_vtep = fields.StringField()

#     @property
#     def ip(self):
#         try:
#             return self.ip_list[0]
#         except IndexError:
#             return None

#     @property
#     def mac(self):
#         try:
#             return self.macs[0]
#         except IndexError:
#             return None
