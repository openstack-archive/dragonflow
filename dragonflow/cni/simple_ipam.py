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

import netaddr

from dragonflow.db.models import ipam
from dragonflow.db.models import l2


def add_subnet_ipam(nb_api, subnet_id):
    lean_subnet = l2.Subnet(id=subnet_id)
    subnet = nb_api.get(lean_subnet)
    ip_set = netaddr.IPSet(subnet.cidr)
    ip_set.remove(subnet.cidr.ip)
    ip_set.remove(subnet.cidr.broadcast)
    ipam_obj = ipam.IPAM(id=subnet_id,
                         free_addrs=[cidr for cidr in ip_set.iter_cidrs()],
                         cidr=subnet.cidr)
    nb_api.create(ipam_obj)


def request_ip(nb_api, subnet_id):
    lean_ipam = ipam.IPAM(id=subnet_id)
    ipam_object = nb_api.get(lean_ipam)
    ipset = netaddr.IPSet(ipam_object.free_addrs)
    try:
        ret = next(ipset.__iter__())
    except StopIteration:
        return None
    ipset.remove(ret)
    ipam_object.free_addrs = [cidr for cidr in ipset.iter_cidrs()]
    nb_api.update(ipam_object)
    return ret


def release_ip(nb_api, subnet_id, ip):
    lean_ipam = ipam.IPAM(id=subnet_id)
    ipam_obj = nb_api.get(lean_ipam)
    if ip not in ipam_obj.cidr:
        raise ValueError(_("trying to release an address"
                           " that is not in the allowed range"))
    ipset = netaddr.IPSet(ipam_obj.free_addrs)
    if ip in ipset:
        raise ValueError(_("trying to release ip that is not in use"))

    ipset.add(ip)
    ipam_obj.free_addrs = [cidr for cidr in ipset.iter_cidrs()]
    nb_api.update(ipam_obj)
