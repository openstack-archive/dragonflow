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

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import core
from dragonflow.db.models import host_route
from dragonflow.db.models import l2
from dragonflow.db.models import mixins


@mf.construct_nb_db_model
class LogicalRouterPort(mf.ModelBase, mixins.Topic, mixins.UniqueKey):
    mac = fields.StringField()
    lswitch = df_fields.ReferenceField(l2.LogicalSwitch)
    network = df_fields.IpNetworkField()


@mf.register_model
@mf.construct_nb_db_model
class LogicalRouter(mf.ModelBase, mixins.Name, mixins.Version, mixins.Topic,
                    mixins.UniqueKey, mixins.BasicEvents):
    """Define the dragonflow db model for logical router.

    Note that only the fields that dragonflow has used are defined here.
    Fields like 'distributed' and 'external_gateway' are missed on purpose.
    """
    table_name = "lrouter"

    ports = fields.ListField(LogicalRouterPort)
    routes = fields.ListField(host_route.HostRoute)

    def add_router_port(self, router_port):
        self.ports.append(router_port)

    def remove_router_port(self, router_port_id):
        for idx, router_port in enumerate(self.ports):
            if router_port.id == router_port_id:
                self.ports.pop(idx)


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'lport': 'lport.id',
        'floating_lport': 'floating_lport.id',
    },
)
class FloatingIp(mf.ModelBase, mixins.Version, mixins.Topic,
                 mixins.BasicEvents):
    table_name = 'floatingip'

    floating_ip_address = df_fields.IpAddressField()
    fixed_ip_address = df_fields.IpAddressField()
    lport = df_fields.ReferenceField(l2.LogicalPort)
    floating_lport = df_fields.ReferenceField(l2.LogicalPort)
    lrouter = df_fields.ReferenceField(LogicalRouter)


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'lport': 'lport.id',
    },
)
class PAT(mf.ModelBase, mixins.Version, mixins.Topic, mixins.BasicEvents):
    table_name = 'pat'

    ip_address = df_fields.IpAddressField()
    lport = df_fields.ReferenceField(l2.LogicalPort)
    chassis = df_fields.ReferenceField(core.Chassis)


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'pat': 'pat.id',
        'lport': 'lport.id',
    },
)
class PATEntry(mf.ModelBase, mixins.Version, mixins.Topic,
                 mixins.BasicEvents):
    table_name = 'pat_entry'

    pat = df_fields.ReferenceField(PAT)
    pat_l4_port = df_fields.L4PortField()
    fixed_ip_address = df_fields.IpAddressField()
    fixed_l4_port = df_fields.L4PortField()
    lport = df_fields.ReferenceField(l2.LogicalPort)
    lrouter = df_fields.ReferenceField(LogicalRouter)
