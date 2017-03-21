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

#f3rom dragonflow._i18n import _LE
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
        raise ValueError('Reference field should only be initialized by ID or '
                'model instance/reference',
        )

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


class ReferenceListField(fields.ListField):
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
        self._proxy_type = model_proxy.create_model_proxy(
            model_framework.get_model(target_model))
        self._lazy = lazy
        super(ReferenceListField, self).__init__(
            self._proxy_type, *args, **kwargs)

    def parse_value(self, values):
        return [
            _create_ref(self._proxy_type, v, self._lazy) for v in values or []
        ]

    def to_struct(self, objs):
        if objs:
            return [o.id for o in objs]


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
            raise errors.ValidationError('{value} is not one of: [{valid_values}]'.format(
                    value=value,
                    valid_values=', '.join(self._valid_values),
                ),
            )


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
            raise errors.ValidationError('Field is required!')

        if value is None:
            return

        for elem in value:
            if elem not in self._valid_values:
                raise errors.ValidationError('{value} is not one of: [{valid_values}]'.format(
                        value=value,
                        valid_values=', '.join(self._valid_values),
                    ),
                )
