# Copyright (c) 2016 OpenStack Foundation.
# All Rights Reserved.
#
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

import hashlib
import hmac
import httplib2
import netaddr
import six
import six.moves.urllib.parse as urlparse
import webob

from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import importutils

from neutron.agent.ovsdb.native import idlutils

from dragonflow._i18n import _, _LW, _LE
from dragonflow.common.exceptions import LogicalPortNotFoundByTunnelKey
from dragonflow.common.exceptions import NoRemoteIPProxyException
from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp
from dragonflow.db import api_nb

from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4


LOG = log.getLogger(__name__)

# These two globals are constant, as defined by the metadata service API. VMs
# contact 169.254.169.254:80, despite of where we actually listen to the
# service. This will be modified by flows.
METADATA_SERVICE_IP = '169.254.169.254'
HTTP_PORT = 80
FLOW_IDLE_TIMEOUT = 60

# TODO(oanson) The TCP_* flag constants have already made it into ryu
# master, but not to pip. Once that is done, they should be taken from
# there. (ryu.lib.packet.tcp.TCP_SYN and ryu.lib.packet.tcp.TCP_ACK)
TCP_SYN = 0x002
TCP_ACK = 0x010


options = [
    cfg.IPOpt(
        'ip',
        default='169.254.169.254',
        help=_('The IP to which the DF metadata service proxy is bound'),
    ),
    cfg.PortOpt(
        'port',
        default='18080',
        help=_('The port to which the DF metadata service proxy is bound'),
    ),
    cfg.StrOpt(
        'interface',
        default='tap-metadata',
        help=_('The name of the interface to bind the metadata service proxy'),
    ),
]


class MetadataServiceApp(DFlowApp):
    def __init__(self, api, db_store=None, vswitch_api=None, nb_api=None):
        super(MetadataServiceApp, self).__init__(
            api,
            db_store=db_store,
            vswitch_api=vswitch_api,
            nb_api=nb_api
        )
        self._arp_responder = None
        self._ofport = None
        cfg.CONF.register_opts(options, group='df_metadata')
        self._ip = cfg.CONF.df_metadata.ip
        self._port = cfg.CONF.df_metadata.port
        self._interface = cfg.CONF.df_metadata.interface

    def ovs_sync_started(self):
        self.initialize()

    def initialize(self):
        loopingcall.FixedIntervalLoopingCall(
            self._wait_for_tap_metadata_interface
        ).start(0, 1)

    def _wait_for_tap_metadata_interface(self):
        idl = self.vswitch_api.idl
        if not idl:
            return
        interface = idlutils.row_by_value(
            idl,
            'Interface',
            'name',
            self._interface,
            None,
        )
        if not interface:
            return
        ofport = interface.ofport
        if not ofport:
            return
        if isinstance(ofport, list):
            ofport = ofport[0]
        if ofport <= 0:
            return
        self._add_tap_metadata_port(ofport, interface.mac_in_use[0])
        raise loopingcall.LoopingCallDone()

    def _add_tap_metadata_port(self, ofport, mac):
        """
        Add the flows that can be added with the current available information:
        Regular Client->Server packets have IP rewritten, and sent to OVS port
        TCP Syn packets are sent to controller, so that response flows can be
            added.
        Packets from the OVS port are detected and sent for classification.
        """
        self._ofport = ofport
        datapath = self.get_datapath()
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self._add_incoming_flows()
        # Regular packet
        match = parser.OFPMatch(eth_type=ethernet.ether.ETH_TYPE_IP)
        actions = self._get_rewrite_ip_and_output_actions(ofproto, parser)
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS,
            actions,
        )]
        self.mod_flow(
            datapath=datapath,
            table_id=const.METADATA_SERVICE_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            inst=inst,
        )
        # TCP SYN packet
        match = parser.OFPMatch(
            eth_type=ethernet.ether.ETH_TYPE_IP,
            ip_proto=ipv4.inet.IPPROTO_TCP,
            tcp_flags=(TCP_SYN, TCP_SYN | TCP_ACK),
        )
        learn_actions = self._get_learn_actions(ofproto, parser)
        learn_actions.extend(actions)
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS,
            learn_actions,
        )]
        self.mod_flow(
            datapath=datapath,
            table_id=const.METADATA_SERVICE_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_HIGH,
            match=match,
            inst=inst,
        )
        # Response packet
        actions = [
            parser.NXActionRegLoad(0, 31, 'in_port', 0),
        ]
        inst = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions,
            ),
            parser.OFPInstructionGotoTable(const.METADATA_SERVICE_REPLY_TABLE),
        ]
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=parser.OFPMatch(in_port=ofport),
            inst=inst,
        )
        self._create_arp_responder(mac)

    def _add_incoming_flows(self):
        datapath = self.get_datapath()
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=ethernet.ether.ETH_TYPE_IP,
            ipv4_dst=METADATA_SERVICE_IP,
            ip_proto=ipv4.inet.IPPROTO_TCP,
            tcp_dst=HTTP_PORT,
        )

        inst = self._get_incoming_flow_instructions(ofproto, parser)
        self.mod_flow(
            datapath=datapath,
            table_id=const.SERVICES_CLASSIFICATION_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            inst=inst)

    def _get_incoming_flow_instructions(self, ofproto, parser):
        actions = self._get_incoming_flow_actions(ofproto, parser)
        inst = []
        if actions:
            inst.append(
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    actions
                ),
            )
        inst.append(
            parser.OFPInstructionGotoTable(const.METADATA_SERVICE_TABLE)
        )
        return inst

    def _get_incoming_flow_actions(self, ofproto, parser):
        actions = []
        if self._ip != METADATA_SERVICE_IP:
            actions.append(parser.OFPActionSetField(ipv4_dst=self._ip))
        if self._port != HTTP_PORT:
            actions.append(parser.OFPActionSetField(tcp_dst=self._port))
        actions.append(parser.OFPActionSetField(reg7=self._ofport))
        return actions

    def _get_rewrite_ip_and_output_actions(self, ofproto, parser):
        """
        Retrieve the actions that rewrite the dst IP field with the reg6
        (the tunnel key), set the first bit of that field, and output to the
        metadata service OVS port.
        The IP is set to <reg6> | 0x8000000, so that the transparent proxy
        can extract the <reg6> from the source IP address, and be able to
        identify the source VM. reg6 holds the local DF id identifying the VM.
        """
        return [
            parser.NXActionRegMove(
                src_field='reg6',
                dst_field='ipv4_src',
                n_bits=32,
            ),
            parser.NXActionRegLoad(31, 31, 'ipv4_src', 1),
            parser.OFPActionOutput(
                self._ofport,
                ofproto.OFPCML_NO_BUFFER,
            )
        ]

    def _get_learn_actions(self, ofproto, parser):
        return [
            # Return flow
            parser.NXActionLearn(
                table_id=const.METADATA_SERVICE_REPLY_TABLE,
                specs=[
                    # Match
                    parser.NXFlowSpecMatch(
                        src=ethernet.ether.ETH_TYPE_IP,
                        dst=('eth_type', 0),
                        n_bits=16,
                    ),
                    parser.NXFlowSpecMatch(
                        src=ipv4.inet.IPPROTO_TCP,
                        dst=('ip_proto', 0),
                        n_bits=8,
                    ),
                    parser.NXFlowSpecMatch(
                        src=1,
                        dst=('ipv4_dst', 31),
                        n_bits=1,
                    ),
                    parser.NXFlowSpecMatch(
                        src=('reg6', 0),
                        dst=('ipv4_dst', 0),
                        n_bits=31,
                    ),
                    parser.NXFlowSpecMatch(
                        src=('tcp_src', 0),
                        dst=('tcp_dst', 0),
                        n_bits=16,
                    ),
                    # Actions
                    parser.NXFlowSpecLoad(
                        src=('ipv4_src', 0),
                        dst=('ipv4_dst', 0),
                        n_bits=32,
                    ),
                    parser.NXFlowSpecLoad(
                        src=int(netaddr.IPAddress(METADATA_SERVICE_IP)),
                        dst=('ipv4_src', 0),
                        n_bits=32,
                    ),
                    parser.NXFlowSpecLoad(
                        src=HTTP_PORT,
                        dst=('tcp_src', 0),
                        n_bits=16,
                    ),
                    parser.NXFlowSpecOutput(
                        src=('in_port', 0),
                        dst='',
                        n_bits=32,
                    ),
                ],
                fin_idle_timeout=1,
                fin_hard_timeout=1,
            ),
            # ARP responder
            parser.NXActionLearn(
                table_id=const.METADATA_SERVICE_REPLY_TABLE,
                priority=const.PRIORITY_HIGH,
                specs=[
                    # Match
                    parser.NXFlowSpecMatch(
                        src=ethernet.ether.ETH_TYPE_ARP,
                        dst=('eth_type', 0),
                        n_bits=16,
                    ),
                    parser.NXFlowSpecMatch(
                        src=('reg6', 0),
                        dst=('arp_tpa', 0),
                        n_bits=31,
                    ),
                    parser.NXFlowSpecMatch(
                        src=arp.ARP_REQUEST,
                        dst=('arp_op', 0),
                        n_bits=8,
                    ),
                    # Actions
                    parser.NXFlowSpecLoad(
                        src=0,
                        dst=('reg6', 0),
                        n_bits=32,
                    ),
                    parser.NXFlowSpecLoad(
                        src=arp.ARP_REPLY,
                        dst=('arp_op', 0),
                        n_bits=8,
                    ),
                    parser.NXFlowSpecLoad(
                        src=('eth_dst', 0),
                        dst=('arp_tha', 0),
                        n_bits=48,
                    ),
                    parser.NXFlowSpecLoad(
                        src=int(netaddr.IPAddress(self._ip)),
                        dst=('arp_tpa', 0),
                        n_bits=32,
                    ),
                    parser.NXFlowSpecLoad(
                        src=('eth_src', 0),
                        dst=('eth_src', 0),
                        n_bits=48,
                    ),
                    parser.NXFlowSpecLoad(
                        src=('eth_src', 0),
                        dst=('arp_sha', 0),
                        n_bits=48,
                    ),
                    parser.NXFlowSpecLoad(
                        src=('reg6', 0),
                        dst=('arp_spa', 0),
                        n_bits=32,
                    ),
                    parser.NXFlowSpecLoad(
                        src=1,
                        dst=('arp_spa', 31),
                        n_bits=1,
                    ),
                    parser.NXFlowSpecOutput(
                        src=('reg7', 0),
                        dst='',
                        n_bits=32,
                    ),
                ],
                idle_timeout=30,
            )
        ]

    def _create_arp_responder(self, mac):
        self._arp_responder = ArpResponder(
            self.get_datapath(),
            None,
            METADATA_SERVICE_IP,
            mac
        )
        self._arp_responder.add()


class BaseMetadataProxyHandler(object):

    @webob.dec.wsgify(RequestClass=webob.Request)
    def __call__(self, req):
        try:
            LOG.debug("Request: %s", req)
            return self.proxy_request(req)
        except Exception:
            LOG.exception(_LE("Unexpected error."))
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            explanation = six.text_type(msg)
            return webob.exc.HTTPInternalServerError(explanation=explanation)

    def proxy_request(self, req):
        headers = self.get_headers(req)
        url = urlparse.urlunsplit((
            self.get_scheme(req),
            self.get_host(req),
            self.get_path_info(req),
            self.get_query_string(req),
            ''))
        h = self.create_http_client(req)
        resp, content = h.request(
            url,
            method=req.method,
            headers=headers,
            body=req.body
        )
        if resp.status == 200:
            LOG.debug(str(resp))
            return self.create_response(req, resp, content)
        elif resp.status == 403:
            LOG.warning(_LW(
                'The remote metadata server responded with Forbidden. This '
                'response usually occurs when shared secrets do not match.'
            ))
            return webob.exc.HTTPForbidden()
        elif resp.status == 400:
            return webob.exc.HTTPBadRequest()
        elif resp.status == 404:
            return webob.exc.HTTPNotFound()
        elif resp.status == 409:
            return webob.exc.HTTPConflict()
        elif resp.status == 500:
            msg = _LW(
                'Remote metadata server experienced an internal server error.'
            )
            LOG.warning(msg)
            explanation = six.text_type(msg)
            return webob.exc.HTTPInternalServerError(explanation=explanation)
        else:
            raise Exception(_('Unexpected response code: %s') % resp.status)

    def get_headers(self, req):
        return req.headers

    def create_response(self, req, resp, content):
        req.response.content_type = resp['content-type']
        req.response.body = content
        return req.response

    def get_scheme(self, req):
        return req.scheme

    def get_host(self, req):
        return req.host

    def get_path_info(self, req):
        return req.path

    def get_query_string(self, req):
        return req.query_string

    def create_http_client(self, req):
        return httplib2.Http()


class DFMetadataProxyHandler(BaseMetadataProxyHandler):
    def __init__(self, conf):
        super(DFMetadataProxyHandler, self).__init__()
        self.conf = conf
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(
            nb_driver_class(),
            use_pubsub=cfg.CONF.df.enable_df_pub_sub)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

    def _get_ovsdb_connection_string(self):
        return 'tcp:{}:6640'.format(cfg.CONF.df.local_ip)

    def get_headers(self, req):
        remote_addr = req.remote_addr
        if not remote_addr:
            raise NoRemoteIPProxyException()
        tunnel_key = int(netaddr.IPAddress(remote_addr) & ~0x80000000)
        lport = self._get_logical_port_by_tunnel_key(tunnel_key)
        headers = dict(req.headers)
        tenant_id = lport.get_topic()
        instance_id = lport.get_device_id()
        ip = lport.get_ip()
        headers.update({
            'X-Forwarded-For': ip,
            'X-Tenant-ID': tenant_id,
            'X-Instance-ID': instance_id,
            'X-Instance-ID-Signature': self._sign_instance_id(instance_id),
        })
        return headers

    def get_host(self, req):
        return '{}:{}'.format(
            self.conf.nova_metadata_ip,
            self.conf.nova_metadata_port,
        )

    def get_scheme(self, req):
        return self.conf.nova_metadata_protocol

    def create_http_client(self, req):
        h = httplib2.Http(
            ca_certs=self.conf.auth_ca_cert,
            disable_ssl_certificate_validation=self.conf.nova_metadata_insecure
        )
        if self.conf.nova_client_cert and self.conf.nova_client_priv_key:
            h.add_certificate(self.conf.nova_client_priv_key,
                              self.conf.nova_client_cert,
                              self.get_host(req))
        return h

    def _get_logical_port_by_tunnel_key(self, tunnel_key):
        lports = self.nb_api.get_all_logical_ports()
        for lport in lports:
            if lport.get_tunnel_key() == tunnel_key:
                return lport
        raise LogicalPortNotFoundByTunnelKey(key=tunnel_key)

    # Taken from Neurton: neutron/agent/metadata/agent.py
    def _sign_instance_id(self, instance_id):
        secret = self.conf.metadata_proxy_shared_secret
        secret = encodeutils.to_utf8(secret)
        instance_id = encodeutils.to_utf8(instance_id)
        return hmac.new(secret, instance_id, hashlib.sha256).hexdigest()
