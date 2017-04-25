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

from oslo_serialization import jsonutils


UNIQUE_KEY = 'unique_key'

table_class_mapping = {}


def register_model_class(cls):
    table_class_mapping[cls.table_name] = cls
    return cls


class NbObject(object):

    def __init__(self, inner_obj):
        super(NbObject, self).__init__()
        self.inner_obj = inner_obj

    def get_id(self):
        """Return the ID of this object."""
        return self.inner_obj.get('id')

    @property
    def id(self):
        return self.get_id()

    @classmethod
    def from_json(cls, value):
        # Added to imitate new style objects
        return cls(value)

    def get_topic(self):
        """
        Return the topic, i.e. ID of the tenant to which this object belongs.
        """
        return self.inner_obj.get('topic')

    def __str__(self):
        return str(self.inner_obj)

    # NOTE(xiaohhui): In python3, add customized __eq__ will make object
    # unhashable. If the models in this module need to be hashable, customized
    # __hash__ will be required.
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.inner_obj == other.inner_obj
        else:
            return False


class NbDbObject(NbObject):

    table_name = "df_nb_object"

    def __init__(self, value):
        inner_obj = jsonutils.loads(value)
        super(NbDbObject, self).__init__(inner_obj)

    def get_name(self):
        return self.inner_obj.get('name')

    def get_version(self):
        return self.inner_obj.get('version')

    @property
    def version(self):
        return self.get_version()


class UniqueKeyMixin(object):

    def get_unique_key(self):
        return self.inner_obj.get(UNIQUE_KEY)


@register_model_class
class Floatingip(NbDbObject):

    table_name = "floatingip"

    def get_status(self):
        return self.inner_obj.get('status')

    def update_fip_status(self, status):
        self.inner_obj['status'] = status

    def get_ip_address(self):
        return self.inner_obj.get('floating_ip_address')

    def get_mac_address(self):
        return self.inner_obj.get('floating_mac_address')

    def get_lport_id(self):
        return self.inner_obj.get('port_id')

    def get_fixed_ip_address(self):
        return self.inner_obj.get('fixed_ip_address')

    def get_lrouter_id(self):
        return self.inner_obj.get('router_id')

    def get_external_gateway_ip(self):
        return self.inner_obj.get('external_gateway_ip')

    def set_external_gateway_ip(self, gw_ip):
        self.inner_obj['external_gateway_ip'] = gw_ip

    def get_floating_network_id(self):
        return self.inner_obj.get('floating_network_id')

    def get_external_cidr(self):
        return self.inner_obj.get('external_cidr')

    def get_floating_port_id(self):
        return self.inner_obj.get('floating_port_id')


@register_model_class
class AllowedAddressPairsActivePort(NbDbObject):

    table_name = "activeport"

    def get_id(self):
        id = self.inner_obj.get('network_id') + self.inner_obj.get('ip')
        return id

    def get_ip(self):
        return self.inner_obj.get('ip')

    def get_network_id(self):
        return self.inner_obj.get('network_id')

    def get_detected_mac(self):
        return self.inner_obj.get('detected_mac')

    def get_detected_lport_id(self):
        return self.inner_obj.get('detected_lport_id')

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            if (self.get_network_id() == other.get_network_id() and
                self.get_ip() == other.get_ip() and
                self.get_detected_mac() == other.get_detected_mac() and
                self.get_topic() == other.get_topic() and
                (self.get_detected_lport_id() ==
                 other.get_detected_lport_id())):
                return True
        return False

    def __ne__(self, other):
        if self == other:
            return False
        return True
