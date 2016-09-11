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
from oslo_utils import importutils

from dragonflow._i18n import _, _LE
from dragonflow.common import exceptions

LOG = log.getLogger(__name__)


class AppDispatcher(object):

    def __init__(self, apps_location_prefix, app_list):
        self.apps_location_prefix = apps_location_prefix
        self.apps_list = app_list.split(',')
        self.apps = []

    def load(self, *args, **kwargs):
        for app in self.apps_list:
            app_class_name = self.apps_location_prefix + "." + app
            try:
                app_class = importutils.import_class(app_class_name)
                app = app_class(*args, **kwargs)
                self.apps.append(app)
            except ImportError as e:
                LOG.exception(_LE("Error loading application by class, %s"), e)
                raise ImportError(_("Application class not found."))

    def dispatch(self, method, *args, **kwargs):
        errors = []
        for app in self.apps:
            handler = getattr(app, method, None)
            if handler is not None:
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    app_name = app.__class__.__name__
                    LOG.exception(_LE("Dragonflow application '%(name)s' "
                                      "failed in %(method)s"),
                                  {'name': app_name, 'method': method})
                    errors.append(e)

        if errors:
            raise exceptions.DFMultipleExceptions(errors)
