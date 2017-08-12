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
'''Port binding lookup

Logical port objects have binding field that describe where and how a port is
bound. An application can decide to augment this field locally, e.g.

* Trunk subport is not bound, but trunk app will bind those on the same chassis
  as the parent port.
* Same with DNAT app: floating port will be bound similartly as the target port

This module serves as a global lookup for all apps.
'''

_locations = {}


def reset():
    _locations.clear()


def set_port_binding(lport, binding):
    _locations[lport.id] = binding


def copy_port_binding(lport, source):
    set_port_binding(lport, get_port_binding(source))


def clear_port_binding(lport):
    _locations.pop(lport.id)


def get_port_binding(lport):
    return _locations.get(lport.id, lport.binding)


def is_port_local(lport):
    binding = get_port_binding(lport)
    if binding is not None:
        return binding.is_local
    return False


def is_port_remote(lport):
    binding = get_port_binding(lport)
    if binding is not None:
        return not binding.is_local
    return False
