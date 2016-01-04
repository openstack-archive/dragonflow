# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from oslo_log import log as logging
from oslo_utils import importutils
from stevedore import driver
import sys

from neutron._i18n import _, _LE

DF_PUBSUB_DRIVER_NAMESPACE = 'neutron.df.pubsub_driver'
LOG = logging.getLogger(__name__)


def load_driver(driver_cfg, namespace):
    try:
        # Try to resolve class by alias
        mgr = driver.DriverManager(namespace, driver_cfg)
        class_to_load = mgr.driver
    except RuntimeError:
        e1_info = sys.exc_info()
        # try with class name
        try:
            class_to_load = importutils.import_class(driver_cfg)
        except (ImportError, ValueError):
            LOG.error(_LE("Error loading class by alias"),
                      exc_info=e1_info)
            LOG.error(_LE("Error loading class by class name"),
                      exc_info=True)
            raise ImportError(_("Class not found."))
    return class_to_load()
