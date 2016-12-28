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

from dragonflow._i18n import _LE
from dragonflow.db import model_framework
from dragonflow.db import model_proxy


class ReferenceField(fields.BaseField):
    def __init__(self, model, lazy=True, *args, **kwargs):
        super(ReferenceField, self).__init__(*args, **kwargs)
        self._model = model
        self._lazy = lazy
        # We delay type creation until first access in case model is not
        # available yet
        self._proxy_type_cls = None

    def validate(self, value):
        pass

    @property
    def _proxy_type(self):
        if self._proxy_type_cls is None:
            self._proxy_type_cls = model_proxy.create_model_proxy(
                model_framework.get_model(self._model))
        return self._proxy_type_cls

    def __set__(self, instance, key):
        proxied_obj = self._proxy_type(key, self._lazy)
        super(ReferenceField, self).__set__(instance, proxied_obj)

    def to_struct(self, value):
        return value.id


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
    types = (str, unicode)

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
        super(EnumListField, self).__init__((str, unicode), *args, **kwargs)
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
