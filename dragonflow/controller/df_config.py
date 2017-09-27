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


from neutron.common import config as common_config

from dragonflow.common import profiler as df_profiler
from dragonflow import conf as cfg


def init(argv):
    common_config.init(argv[1:])
    common_config.setup_logging()
    df_profiler.setup(argv[0], cfg.CONF.host)
