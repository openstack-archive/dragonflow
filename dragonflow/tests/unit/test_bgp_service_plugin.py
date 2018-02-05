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

import collections
import mock
from oslo_config import cfg
import uuid

#from neutron.services.trunk import constants as trunk_const
#from neutron.services.trunk import drivers as trunk_drivers
#from neutron.services.trunk import plugin as trunk_plugin
import netaddr
from neutron_dynamic_routing.extensions import bgp
from neutron_lib.api.definitions import portbindings
from neutron_lib import constants
from neutron_lib import context as n_context
from neutron_lib.plugins import directory
from neutron.objects import router as l3_obj
from neutron.tests.unit.api import test_extensions
from neutron.tests.unit.extensions import test_l3

from dragonflow.neutron.common import constants as df_const
from dragonflow.neutron.db.models import l2
from dragonflow.neutron.services.bgp import bgp_plugin
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_mech_driver


MockBGPSpeaker = collections.namedtuple('MockBGPSpeaker', ('id', 'project_id'))


class TestDFBGPServicePlugin(test_mech_driver.DFMechanismDriverTestCase):
    def setUp(self):
        self._extension_drivers.append(bgp.BGP_EXT_ALIAS)
        super(TestDFBGPServicePlugin, self).setUp()
        self.bgp_plugin = bgp_plugin.DFBgpPlugin()

    def _make_floating_ip(self, port_id):
        l3p = directory.get_plugin('L3_ROUTER_NAT')
        kwargs = {'arg_list': ('router:external',),
                  'router:external': True}
        with self.network(**kwargs) as n:
            with self.subnet(network=n) as s:
                with self.port(network=n) as p:
                    fixed_ips = p['port']['fixed_ips']
                    floating_ip_address = fixed_ips[0]['ip_address']
                    flip = l3_obj.FloatingIP(
                            self.context,
                            floating_ip_address=floating_ip_address,
                            floating_network_id=n['network']['id'],
                            floating_port_id=p['port']['id'],
                            fixed_port_id=port_id)
                    flip.create()
        return flip

    def test_floatingip_update_callback_associate(self):
        _get_external_ip_of_lport_patcher = mock.patch.object(
            self.bgp_plugin, '_get_external_ip_of_lport')
        _get_external_ip_of_lport = _get_external_ip_of_lport_patcher.start()
        self.addCleanup(_get_external_ip_of_lport_patcher.stop)
        _add_bgp_speaker_fip_route_patcher = mock.patch.object(
            self.bgp_plugin, '_add_bgp_speaker_fip_route')
        _add_bgp_speaker_fip_route = _add_bgp_speaker_fip_route_patcher.start()
        self.addCleanup(_add_bgp_speaker_fip_route_patcher.stop)
        _bgp_speakers_for_gw_network_by_family_patcher = mock.patch.object(
            self.bgp_plugin, '_bgp_speakers_for_gw_network_by_family')
        _bgp_speakers_for_gw_network_by_family = (
            _bgp_speakers_for_gw_network_by_family_patcher.start())
        self.addCleanup(_bgp_speakers_for_gw_network_by_family_patcher.stop)
        with self.port() as p:
            port = p['port']
            fip = self._make_floating_ip(port['id'])
            _get_external_ip_of_lport.return_value = None
            self.bgp_plugin.floatingip_update_callback(
                mock.sentinel, mock.sentinel, mock.sentinel,
                context=self.context,
                **fip)
            _add_bgp_speaker_fip_route.assert_not_called()
            _bgp_speakers_for_gw_network_by_family.assert_not_called()

            external_ip = netaddr.IPAddress('172.24.4.3')
            _get_external_ip_of_lport.return_value = external_ip
            speaker = MockBGPSpeaker('speaker_id', 'speaker_project')
            _bgp_speakers_for_gw_network_by_family.return_value = [speaker]

            n_context_admin_context_patcher = mock.patch.object(
                n_context, 'get_admin_context')
            n_context_admin_context = n_context_admin_context_patcher.start()
            n_context_admin_context.return_value = 'admin_context'
            self.addCleanup(n_context_admin_context_patcher.stop)

            self.bgp_plugin.floatingip_update_callback(
                mock.sentinel, mock.sentinel, mock.sentinel,
                context=self.context,
                **fip)
            destination = str(netaddr.IPNetwork(fip['floating_ip_address']))
            fip_data = {'destination': destination,
                        'nexthop': external_ip}
            _add_bgp_speaker_fip_route.assert_called_once_with(
                self.context,
                'speaker_id',
                'speaker_project',
                fip_data
            )
            _bgp_speakers_for_gw_network_by_family.assert_called_once_with(
                'admin_context',
                fip['floating_network_id'],
                constants.IP_VERSION_4,
            )

    def test_floatingip_update_callback_disassociate(self):
        _get_external_ip_of_lport_patcher = mock.patch.object(
            self.bgp_plugin, '_get_external_ip_of_lport')
        _get_external_ip_of_lport = _get_external_ip_of_lport_patcher.start()
        self.addCleanup(_get_external_ip_of_lport_patcher.stop)
        _del_bgp_speaker_fip_route_patcher = mock.patch.object(
            self.bgp_plugin, '_del_bgp_speaker_fip_route')
        _del_bgp_speaker_fip_route = _del_bgp_speaker_fip_route_patcher.start()
        self.addCleanup(_del_bgp_speaker_fip_route_patcher.stop)
        _bgp_speakers_for_gw_network_by_family_patcher = mock.patch.object(
            self.bgp_plugin, '_bgp_speakers_for_gw_network_by_family')
        _bgp_speakers_for_gw_network_by_family = (
            _bgp_speakers_for_gw_network_by_family_patcher.start())
        self.addCleanup(_bgp_speakers_for_gw_network_by_family_patcher.stop)

        fip = self._make_floating_ip(None)

        speaker = MockBGPSpeaker('speaker_id', 'speaker_project')
        _bgp_speakers_for_gw_network_by_family.return_value = [speaker]

        n_context_admin_context_patcher = mock.patch.object(
            n_context, 'get_admin_context')
        n_context_admin_context = n_context_admin_context_patcher.start()
        n_context_admin_context.return_value = 'admin_context'
        self.addCleanup(n_context_admin_context_patcher.stop)

        self.bgp_plugin.floatingip_update_callback(
            mock.sentinel, mock.sentinel, mock.sentinel,
            context=self.context,
            **fip)
        _get_external_ip_of_lport.assert_not_called()
        destination = str(netaddr.IPNetwork(fip['floating_ip_address']))
        _del_bgp_speaker_fip_route.assert_called_once_with(
            self.context,
            'speaker_id',
            'speaker_project',
            destination
        )
        _bgp_speakers_for_gw_network_by_family.assert_called_once_with(
            'admin_context',
            fip['floating_network_id'],
            constants.IP_VERSION_4,
        )

    def test__get_external_ip_of_lport(self):
        _get_external_ip_by_host_patcher = mock.patch.object(
            self.bgp_plugin, '_get_external_ip_by_host')
        _get_external_ip_by_host = _get_external_ip_by_host_patcher.start()
        self.addCleanup(_get_external_ip_by_host_patcher.stop)

        kwargs = {
            portbindings.PROFILE: None,
            portbindings.HOST_ID: None
        }
        arg_list = (portbindings.PROFILE, portbindings.HOST_ID)
        with self.port(arg_list=arg_list, **kwargs) as p:
            external_ip = self.bgp_plugin._get_external_ip_of_lport(
                self.context, p['port']['id'])
            self.assertIsNone(external_ip)

        kwargs[portbindings.HOST_ID] = 'dummy_chassis'
        with self.port(arg_list=arg_list, **kwargs) as p:
            _get_external_ip_by_host.return_value = netaddr.IPAddress(
                '1.2.3.4')
            external_ip = self.bgp_plugin._get_external_ip_of_lport(
                self.context, p['port']['id'])
            self.assertEqual(netaddr.IPAddress('1.2.3.4'), external_ip)

        profile = {
            df_const.DF_BINDING_PROFILE_PORT_KEY: df_const.DF_REMOTE_PORT_TYPE,
            df_const.DF_BINDING_PROFILE_HOST_IP: '1.2.3.5'
        }
        kwargs[portbindings.HOST_ID] = None
        kwargs[portbindings.PROFILE] = profile
        with self.port(arg_list=arg_list, **kwargs) as p:
            external_ip = self.bgp_plugin._get_external_ip_of_lport(
                self.context, p['port']['id'])
            self.assertEqual(netaddr.IPAddress('1.2.3.5'), external_ip)
