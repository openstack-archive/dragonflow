#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

"""
This is the single point of entry to generate the sample configuration
file for dragonflow. It collects all the necessary info from the other modules
in this package. It is assumed that:

* every other module in this package has a 'list_opts' function which
  return a dict where
  * the keys are strings which are the group names
  * the value of each key is a list of config options for that group
* the dragonflow.conf package doesn't have further packages with config options
* this module is only used in the context of sample file generation
"""

import collections
import imp
import os
import pkgutil

from dragonflow._i18n import _ as _i18

LIST_OPTS_FUNC_NAME = "list_opts"


def list_opts():
    opts = collections.defaultdict(list)
    imported_modules = _import_modules()
    _append_config_options(imported_modules, opts)
    return [(key, val) for key, val in opts.items()]


def _import_modules():
    imported_modules = []
    package_path = os.path.dirname(os.path.abspath(__file__))
    for _, modname, ispkg in pkgutil.iter_modules(path=[package_path]):
        if modname == __name__.split('.')[-1] or ispkg:
            continue

        path = ('%s/%s.py' % (package_path, modname))
        mod = imp.load_source(modname, path)
        if not hasattr(mod, LIST_OPTS_FUNC_NAME):
            msg = _i18("The module '%s' should have a '%s' function which "
                       "returns the config options." % (mod.__name__,
                       LIST_OPTS_FUNC_NAME))
            raise Exception(msg)
        else:
            imported_modules.append(mod)

    return imported_modules


def _append_config_options(imported_modules, config_options):
    for mod in imported_modules:
        configs = mod.list_opts()
        for key, val in configs.items():
            config_options[key].extend(val)
