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

from dragonflow._i18n import _LE
from dragonflow.db import model_framework
from dragonflow.db import model_proxy


class ReferenceField(fields.BaseField):
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
        if value:
            return self.types[0](id=value)

    def to_struct(self, value):
        return value.id


class ReferenceListField(fields.ListField):
    def __init__(self, target_model, *args, **kwargs):
        self._proxy_type = model_proxy.create_model_proxy(
            model_framework.get_model(target_model))
        super(ReferenceListField, self).__init__(
            self._proxy_type, *args, **kwargs)

    def parse_value(self, values):
        return [self._proxy_type(v) for v in values or []]

    def to_struct(self, values):
        if values:
            return [v.id for v in values]


class IpAddressField(fields.BaseField):
    types = (netaddr.IPAddress)

    def parse_value(self, value):
        if value is not None:
            return netaddr.IPAddress(value)

    def to_struct(self, value):
        if value is not None:
            return str(value)


class IpNetworkField(fields.BaseField):
    types = (netaddr.IPNetwork)

    def parse_value(self, value):
        if value is not None:
            return netaddr.IPNetwork(value)

    def to_struct(self, value):
        if value is not None:
            return str(value)


class EnumField(fields.StringField):
    types = six.string_types

    def __init__(self, values, *args, **kwargs):
        super(EnumField, self).__init__(*args, **kwargs)
        self._valid_values = values

    def validate(self, value):
        super(EnumField, self).validate(value)
        if value is not None and value not in self._valid_values:
            raise errors.ValidationError(
                _LE('{value} is not one of: [{valid_values}]').format(
                    value=value,
                    valid_values=', '.join(self._valid_values),
                ),
            )


class EnumListField(fields.ListField):
    def __init__(self, values, *args, **kwargs):
        super(EnumListField, self).__init__(six.string_types, *args, **kwargs)
        self._valid_values = values

    def validate(self, value):
        if self.required and not value:
            raise errors.ValidationError(_LE('Field is required!'))

        if value is None:
            return

        for elem in value:
            if elem not in self._valid_values:
                raise errors.ValidationError(
                    _LE('{value} is not one of: [{valid_values}]').format(
                        value=value,
                        valid_values=', '.join(self._valid_values),
                    ),
                )


class PortRange(object):
    def __init__(self, min, max):
        self.min = min
        self.max = max


class PortRangeField(fields.BaseField):
    types = (PortRange,)

    def to_struct(self, value):
        if value is None:
            return

        return [value.min, value.max]

    def parse_value(self, value):
        if value is not None:
            return PortRange(value[0], value[1])
