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

from dragonflow._i18n import _
import dragonflow.common.constants as const
from dragonflow.common import dhcp


LOG = log.getLogger(__name__)

dnsmasq_opts = {
    "netmask": 1,
    "router": 3,
    "dns-server": 6,
    "log-server": 7,
    "lpr-server": 9,
    "hostname": 12,
    "domain-name": 15,
    "swap-server": 16,
    "root-path": 17,
    "extension-path": 18,
    "policy-filter": 21,
    "broadcast": 28,
    "router-solicitation": 32,
    "static-route": 33,
    "nis-domain": 40,
    "nis-server": 41,
    "ntp-server": 42,
    "vendor-encap": 43,
    "netbios-ns": 44,
    "netbios-dd": 45,
    "x-windows-fs": 48,
    "x-windows-dm": 49,
    "requested-address": 50,
    "lease-time": 51,
    "option-overload": 52,
    "message-type": 53,
    "server-identifier": 54,
    "parameter-request": 55,
    "message": 56,
    "max-message-size": 57,
    "T1": 58,
    "T2": 59,
    "client-id": 61,
    "nis+-domain": 64,
    "nis+-server": 65,
    "tftp-server": 66,
    "bootfile-name": 67,
    "mobile-ip-home": 68,
    "smtp-server": 69,
    "pop3-server": 70,
    "nntp-server": 71,
    "irc-server": 74,
    "FQDN": 81,
    "agent-id": 82,
    "subnet-select": 118,
    "domain-search": 119,
    "server-ip-address": "siaddr"
}

dhcpd_ops = {
    "subnet-mask": 1,
    "time-offset": 2,
    "routers": 3,
    "time-servers": 4,
    "ien116-name-servers": 5,
    "domain-name-servers": 6,
    "log-servers": 7,
    "cookie-servers": 8,
    "lpr-servers": 9,
    "impress-servers": 10,
    "resource-location-servers": 11,
    "host-name": 12,
    "boot-size": 13,
    "merit-dump": 14,
    "domain-name": 15,
    "swap-server": 16,
    "root-path": 17,
    "extensions-path": 18,
    "ip-forwarding": 19,
    "non-local-source-routing": 20,
    "policy-filter": 21,
    "max-dgram-reassembly": 22,
    "default-ip-ttl": 23,
    "path-mtu-aging-timeout": 24,
    "path-mtu-plateau-table": 25,
    "interface-mtu": 26,
    "all-subnets-local": 27,
    "broadcast-address": 28,
    "perform-mask-discovery": 29,
    "mask-supplier": 30,
    "router-discovery": 31,
    "router-solicitation-address": 32,
    "static-routes": 33,
    "trailer-encapsulation": 34,
    "arp-cache-timeout": 35,
    "ieee802-3-encapsulation": 36,
    "default-tcp-ttl": 37,
    "tcp-keepalive-interval": 38,
    "tcp-keepalive-garbage": 39,
    "nis-domain": 40,
    "nis-servers": 41,
    "ntp-servers": 42,
    "vendor-encapsulated-options": 43,
    "netbios-name-servers": 44,
    "netbios-dd-server": 45,
    "netbios-node-type": 46,
    "netbios-scope": 47,
    "font-servers": 48,
    "x-display-manager": 49,
    "dhcp-requested-address": 50,
    "dhcp-lease-time": 51,
    "dhcp-option-overload": 52,
    "dhcp-message-type": 53,
    "dhcp-server-identifier": 54,
    "dhcp-parameter-request-list": 55,
    "dhcp-message": 56,
    "dhcp-max-message-size": 57,
    "dhcp-renewal-time": 58,
    "dhcp-rebinding-time": 59,
    "vendor-class-identifier": 60,
    "dhcp-client-identifier": 61,
    "nwip-domain": 62,
    "nwip-suboptions": 63,
    "nisplus-domain": 64,
    "nisplus-servers": 65,
    "tftp-server-name": 66,
    "bootfile-name": 67,
    "mobile-ip-home-agent": 68,
    "smtp-server": 69,
    "pop-server": 70,
    "nntp-server": 71,
    "www-server": 72,
    "finger-server": 73,
    "irc-server": 74,
    "streettalk-server": 75,
    "user-class": 77,
    "slp-directory-agent": 78,
    "slp-service-scope": 79,
    "fqdn": 81,
    "relay-agent-information": 82,
    "nds-servers": 85,
    "nds-tree-name": 86,
    "nds-context": 87,
    "bcms-controller-names": 88,
    "bcms-controller-address": 89,
    "client-last-transaction-time": 91,
    "associated-ip": 92,
    "pxe-system-type": 93,
    "pxe-interface-id": 94,
    "pxe-client-id": 97,
    "uap-servers": 98,
    "geoconf-civic": 99,
    "pcode": 100,
    "tcode": 101,
    "netinfo-server-address": 112,
    "netinfo-server-tag": 113,
    "default-url": 114,
    "auto-config": 116,
    "name-service-search": 117,
    "subnet-selection": 118,
    "domain-search": 119,
    "vivco": 124,
    "vivso": 125,
    "pxe-undefined-1": 128,
    "pxe-undefined-2": 129,
    "pxe-undefined-3": 130,
    "pxe-undefined-4": 131,
    "pxe-undefined-5": 132,
    "pxe-undefined-6": 133,
    "pxe-undefined-7": 134,
    "pxe-undefined-8": 135,
    "pana-agent": 136,
    "v4-lost": 137,
    "capwap-ac-v4": 138,
    "sip-ua-cs-domains": 141,
    "ipv4-address-andsf": 142,
    "rdnss-selection": 146,
    "tftp-server-address": 150,
    "v4-portparams": 159,
    "v4-captive-portal": 160,
    "pxelinux-magic": 208,
    "loader-configfile": 209,
    "loader-pathprefix": 210,
    "loader-reboottime": 211,
    "option-6rd": 212,
    "v4-access-domain": 213
}


opt_mapping = {}
opt_mapping.update(dnsmasq_opts)
opt_mapping.update(dhcpd_ops)


def dhcp_app_tag_by_user_tag(usr_tag):
    try:
        user_tag_int = int(usr_tag)
        if dhcp.is_tag_valid(user_tag_int):
            return user_tag_int
    except ValueError:
        pass

    if usr_tag == const.DHCP_SIADDR:
        return usr_tag
    if opt_mapping.get(usr_tag):
        usr_tag_mapps = opt_mapping.get(usr_tag)
    else:
        msg = _("The value of {0} in dhcpd and dnsmasq tags "
                "should not be null").format(usr_tag)
        LOG.exception(msg)
    return usr_tag_mapps
