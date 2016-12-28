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
from dragonflow._i18n import _LE


class _ProxiedField(object):
    def __init__(self, name):
        self._name = name

    def __get__(self, inst, owner=None):
        if inst is not None:
            return getattr(inst.get_object(), self._name)

    def __set__(self, inst, value):
        return setattr(inst.get_object(), self._name, value)


class _ModelProxyBase(object):
    def __init__(self, id, lazy=True):
        self._id = id
        self._obj = None

        if not lazy:
            self.get_object()

    def _fetch_obj(self):
        # Fetch from db_store then from nb api
        pass

    def get_object(self):
        if self._obj is None or self._obj.is_stale():
            self._obj = self._fetch_obj()
        return self._obj

    @property
    def id(self):
        return self._id

    @id.setter
    def ___set_id(self, value):
        raise RuntimeError(_LE('Setting ID of model-proxy is not allowed'))

    def get_field(self, name):
        if name in (self._proxied_attrs + ('id')):
            return getattr(self, name)


def create_model_proxy(model):
    return type(
        '{name}Proxy'.format(name=model.__name__),
        (_ModelProxyBase,),
        {
            name: _ProxiedField(name)
            for name, _ in model.iterate_over_fields()
            if name != 'id'
        },
    )
