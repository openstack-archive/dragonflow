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
from dragonflow.db import db_store2


class _ProxiedField(object):
    '''Descriptor for intercepting access to reference fields and relaying them
    to the actual object.
    '''
    def __init__(self, name):
        self._name = name

    def __get__(self, inst, owner=None):
        if inst is not None:
            return getattr(inst.get_object(), self._name)

    def __set__(self, inst, value):
        return setattr(inst.get_object(), self._name, value)


class _ModelProxyBase(object):
    '''Base for proxy objects

    Responsible for providing direct access to ID field and to fetching the
    backing object on demand.

    Lazyness can be specified on per-instance basis, lazy objects will delay
    fetching the actual model until a field (other than ID) is accessed, eager
    objects will fetch the backing model right away.
    '''

    def __init__(self, id, lazy=True):
        self._id = id
        self._obj = None

        if not lazy:
            self.get_object()

    def _fetch_obj(self):
        obj = db_store2.get_instance().get_one(self._model(id=self._id))
        # FIXME fetch from NbApi
        return obj

    def get_object(self):
        if self._obj is None:
            self._obj = self._fetch_obj()
        return self._obj

    @property
    def id(self):
        return self._id

    @id.setter
    def ___set_id(self, value):
        raise RuntimeError(_LE('Setting ID of model-proxy is not allowed'))

    def to_struct(self):
        return {'id': self._id}


def create_model_proxy(model):
    '''This creates a proxy class for a specific model type, this class can
    then be used to create references.

    >>> LportProxy = create_model_proxy(Lport)
    >>> ref_to_lport = LportProxy(id='some-id')
    >>> ref_to_lport.name
    'port-name'
    '''
    attrs = {
        name: _ProxiedField(name)
        for name, _ in model.iterate_over_fields()
        if name != 'id'
    }

    attrs['_model'] = model

    return type(
        '{name}Proxy'.format(name=model.__name__),
        (_ModelProxyBase,),
        attrs,
    )
