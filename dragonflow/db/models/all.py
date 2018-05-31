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

import stevedore


def load_all_extensions():
    """Load all available modules with DF models"""
    manager = stevedore.ExtensionManager(  # noqa F841
        'dragonflow.db.models',
    )
    # NOTE(oanson) In case Stevedore changes and we need to manually load
    # the extensions:
    # modules = [extension.plugin for extension in manager]

load_all_extensions()
