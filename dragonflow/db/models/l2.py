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

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import host_route
from dragonflow.db.models import mixins
from dragonflow.db.models import qos


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
