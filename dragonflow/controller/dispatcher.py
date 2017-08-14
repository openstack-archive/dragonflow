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

from oslo_log import log
import stevedore

from dragonflow.common import exceptions

LOG = log.getLogger(__name__)


class AppDispatcher(object):

    def __init__(self, app_list):
        self.apps_list = app_list
        self.apps = {}

    def load(self, *args, **kwargs):
        mgr = stevedore.NamedExtensionManager(
            'dragonflow.controller.apps',
            self.apps_list,
            invoke_on_load=True,
            invoke_args=args,
            invoke_kwds=kwargs,
        )

        for ext in mgr:
            self.apps[ext.name] = ext.obj

    def dispatch(self, method, *args, **kwargs):
        errors = []
        for app in self.apps.values():
            handler = getattr(app, method, None)
            if handler is not None:
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    app_name = app.__class__.__name__
                    LOG.exception("Dragonflow application '%(name)s' "
                                  "failed in %(method)s",
                                  {'name': app_name, 'method': method})
                    errors.append(e)

        if errors:
            raise exceptions.DFMultipleExceptions(errors)
