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
from jsonmodels import errors
from jsonmodels import fields
import netaddr
import six

from dragonflow._i18n import _
from dragonflow.common import dhcp
from dragonflow.db import model_framework
from dragonflow.db import model_proxy


def _create_ref(proxy_type, value, lazy):
    """Create a proxy object based on:
        * ID.
        * Another proxy instance.
        * Actual object of the proxied type.

    In case where object is passed (rather than ID), the ID is extracted from
    the relevant field.
    """
    if isinstance(value, six.string_types):
        obj_id = value
    elif isinstance(value, (proxy_type, proxy_type.get_proxied_model())):
        obj_id = value.id
    else:
        raise ValueError(
            _('Reference field should only be initialized by ID or '
              'model instance/reference'))

    return proxy_type(id=obj_id, lazy=lazy)


class ReferenceField(fields.BaseField):
    '''A field that holds a "foreign-key" to another model.

    Used to reference an object stored outside of the model, as if it was
    embedded into it, by creating proxys (with the help of  model_proxy module)

    In serialized form we store just the ID:
        "lswitch": "uuid-of-some-lswitch",

    and in the parsed form holds a proxy to this object:

    >>> obj.lswitch.name
    'some-lswitch'

    '''
    def __init__(self, model, lazy=True, *args, **kwargs):
        super(ReferenceField, self).__init__(*args, **kwargs)
        self._model = model
        self._lazy = lazy
        # We delay type creation until first access in case model is not
        # available yet - i.e we got a string
        self._types = None

    def validate(self, value):
        pass

    @property
    def types(self):
        if self._types is None:
            self._types = (
                model_proxy.create_model_proxy(
                    model_framework.get_model(self._model),
                ),
            )
        return self._types

    def parse_value(self, value):
        if value is None:
            return

        return _create_ref(self.types[0], value, self._lazy)

    def to_struct(self, obj):
        if obj is not None:
            return obj.id


class ListOfField(fields.ListField):
    def __init__(self, field, *args, **kwargs):
        super(ListOfField, self).__init__(
                items_types=field.types, *args, **kwargs)
        if not isinstance(field, fields.BaseField):
            raise TypeError(
                _('field must be an instance of BaseField. Got: %s') %
                (type(field)))
        self.field = field

    def parse_value(self, values):
        if not values:
            return []
        return [self.field.parse_value(value) for value in values]

    def to_struct(self, objs):
        if not objs:
            return []
        return [self.field.to_struct(obj) for obj in objs]


class ReferenceListField(ListOfField):
    '''A field that holds a sequence of 'foreign-keys'

    Much like ReferenceField above, this class allows accessing objects
    referenced by ID as if they were embedded into the model itself.

    Their serialized form is:
        "security_groups": ["secgroupid1", "secgroupid2"],

    And the parsed form is that of a list of proxies:

    >>> obj.security_groups[1].name
    'Name of the secgroup'

    '''
    def __init__(self, target_model, lazy=True, *args, **kwargs):
        super(ReferenceListField, self).__init__(
                ReferenceField(target_model, lazy), *args, **kwargs)


class IpAddressField(fields.BaseField):
    '''A field that holds netaddr.IPAddress

    In serialized form it is stored as IP address string:
        "ip": "10.0.0.12",
    '''
    types = (netaddr.IPAddress,)

    def parse_value(self, value):
        if value is not None:
            return netaddr.IPAddress(value)

    def to_struct(self, obj):
        if obj is not None:
            return str(obj)


class IpNetworkField(fields.BaseField):
    '''A field that holds netaddr.IPNetwork

    In serialized form it is stored as CIDR:
        "network": "10.0.0.0/24",
    '''
    types = (netaddr.IPNetwork,)

    def parse_value(self, value):
        if value is not None:
            return netaddr.IPNetwork(value)

    def to_struct(self, obj):
        if obj is not None:
            return str(obj)


TimestampField = fields.FloatField


class MacAddressField(fields.BaseField):
    '''A field representing a MAC address, specifically a netaddr.EUI.

    In serialized form it is stored in UNIX MAC format:
        "mac": "12:34:56:78:90:ab"
    '''
    types = (netaddr.EUI,)

    def parse_value(self, value):
        if value is not None:
            return netaddr.EUI(value, dialect=netaddr.mac_unix_expanded)

    def to_struct(self, obj):
        if obj is not None:
            obj.dialect = netaddr.mac_unix_expanded
            return str(obj)


class EnumField(fields.StringField):
    '''A field that can hold a string from a set of predetermined values:

    >>> class F(ModelBase):
    ...     f = EnumField(('a', 'b', 'c'))

    >>> F(f='a')  # OK
    >>> F(f='d')  # raises
    Traceback...
      ....
    ValidationError: ...
    '''
    types = six.string_types

    def __init__(self, values, *args, **kwargs):
        super(EnumField, self).__init__(*args, **kwargs)
        self._valid_values = values

    def validate(self, value):
        super(EnumField, self).validate(value)
        if value is not None and value not in self._valid_values:
            raise errors.ValidationError(
                _('{value} is not one of: [{valid_values}]').format(
                    value=value, valid_values=', '.join(self._valid_values)))


class EnumListField(fields.ListField):
    '''A field that stores a list of strings restricted to predetermined values

    Similar to EnumField above, allowed entries in the list are restricted to
    a list provided during field's creation.
    '''
    def __init__(self, values, *args, **kwargs):
        super(EnumListField, self).__init__(six.string_types, *args, **kwargs)
        self._valid_values = values

    def validate(self, value):
        if self.required and not value:
            raise errors.ValidationError(_('Field is required!'))

        if value is None:
            return

        for elem in value:
            if elem not in self._valid_values:
                raise errors.ValidationError(
                    _('{value} is not one of: [{valid_values}]').format(
                        value=value,
                        valid_values=', '.join(self._valid_values)))


class DhcpOptsDictField(fields.BaseField):
    '''A field that stores a  mapping between
    int (represented the dhcp tag) ->
    string (represent the dhcp value)
    '''

    types = (dict,)

    def parse_value(self, value):
        if value is not None:
            return {int(key): inner_val for key, inner_val in value.items()}

    def to_struct(self, obj):
        if obj is not None:
            return {str(key): inner_val for key, inner_val in obj.items()}

    def validate(self, value):
        super(DhcpOptsDictField, self).validate(value)
        if not value:
            return
        for key, inner_val in value.items():
            if not dhcp.is_tag_valid(key):
                raise errors.ValidationError(
                    _('Key {} is not a vaild dhcp opt').format(key))
            if not isinstance(inner_val, six.string_types):
                raise errors.ValidationError(
                    _('Value {value} to key {key} is not a string').format(
                        key=key, value=inner_val))

    def get_default_value(self):
        return {}


class PortRange(object):
    def __init__(self, port_min, port_max):
        self.min = port_min
        self.max = port_max

    @classmethod
    def from_min_max(cls, port_min, port_max):
        if port_min is not None and port_max is not None:
            return cls(port_min, port_max)

    def __eq__(self, other):
        if type(other) != PortRange:
            return False
        return (self.min, self.max) == (other.min, other.max)

    def __ne__(self, other):
        return not (self == other)


class PortRangeField(fields.BaseField):
    types = (PortRange,)

    def to_struct(self, value):
        if value is None or value == [None, None]:
            return

        return [value.min, value.max]

    def parse_value(self, value):
        if value is not None:
            if isinstance(value, PortRange):
                return value
            else:
                # Raise an error if list in not of 2 values
                port_min, port_max = value
                return PortRange(port_min, port_max)


class IpProto(fields.IntField):

    def validate(self, value):
        super(IpProto, self).validate(value)
        if value is None:
            return
        if value < 0 or value > 255:
            raise errors.ValidationError(
                _('IP protocol value must to be in the'
                  ' range [0,255] ({val} supplied )'
                  ).format(
                    val=value))
