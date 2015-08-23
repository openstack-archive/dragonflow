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

import time

from oslo_log import log
from oslo_utils import importutils

from neutron.i18n import _, _LE

from ryu.base.app_manager import AppManager
from ryu.controller.ofp_handler import OFPHandler

LOG = log.getLogger(__name__)


class AppDispatcher(object):

    def __init__(self, apps_location_prefix, app_list, params):
        self.apps_location_prefix = apps_location_prefix
        self.apps_list = app_list.split(',')
        self.params = params
        self.apps = []

    def load(self):
        app_mgr = AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(OFPHandler, None, None)
        self.open_flow_app.start()

        for app in self.apps_list:
            app_class_name = self.apps_location_prefix + "." + app
            try:
                app_class = importutils.import_class(app_class_name)
                app = app_mgr.instantiate(app_class, None, **self.params)
                app.start()
                self.apps.append(app)
            except ImportError as e:
                LOG.exception(_LE("Error loading application by class, %s"), e)
                raise ImportError(_("Application class not found."))

    def dispatch(self, method, **args):
        for app in self.apps:
            handler = getattr(app, method, None)
            if handler is not None:
                handler(**args)

    def is_ready(self):
        while not self._is_ready():
            time.sleep(3)

    def _is_ready(self):
        for app in self.apps:
            handler = getattr(app, 'is_ready')
            if handler is not None:
                is_ready = handler()
                if not is_ready:
                    return False
        return True
