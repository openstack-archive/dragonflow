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
import copy
import six

from oslo_log import log

from dragonflow._i18n import _
from dragonflow.common import exceptions
from dragonflow.db import db_store


LOG = log.getLogger(__name__)


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
        # _model attribute is provided by the deriving class
        obj = db_store.get_instance().get_one(self._model(id=self._id))
        # FIXME fetch from NbApi
        return obj

    def get_object(self):
        if self._obj is None:
            self._obj = self._fetch_obj()
        elif self._obj._is_object_stale:
            self._obj = self._fetch_obj()
        return self._obj

    @property
    def id(self):
        return self._id

    @id.setter
    def id_setter(self, value):
        raise RuntimeError(_('Setting ID of model-proxy is not allowed'))

    def to_struct(self):
        return {'id': self._id}

    @classmethod
    def get_proxied_model(cls):
        return cls._model

    def __repr__(self):
        return '{0}(id={1})'.format(self.__class__.__name__, self._id)

    def __eq__(self, other):
        if type(other) is not type(self):
            return False
        return self._id == other.id

    def __ne__(self, other):
        return not self == other

    def __getattr__(self, name):
        if name == '_obj':
            return
        obj = self.get_object()
        if obj is None:
            raise exceptions.ReferencedObjectNotFound(proxy=self)
        return getattr(obj, name)

    def __copy__(self):
        return self.__class__(self._id)

    def __deepcopy__(self, memo):
        return copy.copy(self)


def _memoize_model_proxies(f):
    """
    A memoization decorator targeted for `create_model_proxy`.
    """
    memo = {}

    @six.wraps(f)
    def func(model):
        try:
            return memo[model]
        except KeyError:
            result = f(model)
            memo[model] = result
            return result
    return func


@_memoize_model_proxies
def create_model_proxy(model):
    '''This creates a proxy class for a specific model type, this class can
    then be used to create references.

    >>> LportProxy = create_model_proxy(Lport)
    >>> ref_to_lport = LportProxy(id='some-id')
    >>> ref_to_lport.name
    'port-name'
    '''
    attrs = {'_model': model}

    return type(
        '{name}Proxy'.format(name=model.__name__),
        (_ModelProxyBase,),
        attrs,
    )


def create_reference(model, id=None, lazy=True, **kwargs):
    """
    Create a reference to an instance of a model. lazy states the entire model
    is retrieved only upon access. If lazy is False, the entire model is read
    upon reference creation

    If kwargs is empty, or no ID field is given in kwargs, None is returned. If
    more granularity is needed, use `create_model_proxy` above.

    >>> ref_to_lport = create_reference(Lport, id='some-id')
    >>> ref_to_lport.name
    'port-name'
    """
    if not id:
        return None
    reference_model = create_model_proxy(model)
    instance = reference_model(lazy=lazy, id=id, **kwargs)
    return instance


def is_model_proxy(model):
    return isinstance(model, _ModelProxyBase)
