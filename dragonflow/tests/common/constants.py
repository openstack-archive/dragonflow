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

# It takes some time from the moment the command is sent out to Neutron/DF DB,
# until it finishes. It shouldn't be more than, say, 5 seconds.
DEFAULT_CMD_TIMEOUT = 5

# It takes some time from the moment the command is sent to Neutron, until
# the resource of Neutron is ready for usage. It shouldn't be more than,
# say, 60 seconds.
DEFAULT_RESOURCE_READY_TIMEOUT = 60

# As we do not want to "choke" the system with polling requests, we would like
# to have some time between checks, say, 5 seconds.
DEFAULT_RESOURCE_READY_SLEEP = 5
