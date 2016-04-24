# Copyright (c) 2015 OpenStack Foundation.
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
import re
import six
import six.moves.urllib.parse as urlparse
import webob

from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import importutils

from neutron.agent.common import utils
from neutron.agent.ovsdb.native import idlutils

from dragonflow._i18n import _, _LW, _LE
from dragonflow.common.exceptions import NoRemoteIPProxyException
from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp
from dragonflow.db import api_nb
from dragonflow.db.drivers import ovsdb_vswitch_impl

from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet


LOG = log.getLogger(__name__)
METADATA_SERVICE_IP = '169.254.169.254'
HTTP_PORT = 80
FLOW_IDLE_TIMEOUT = 60

# TODO(oanson) The TCP_* flag constants have already made it into ryu
# master, but not to pip. Once that is done, they should be taken from
# there. (ryu.lib.packet.tcp.TCP_SYN and ryu.lib.packet.tcp.TCP_ACK)
TCP_SYN = 0x002
TCP_ACK = 0x010


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

        inst = [parser.OFPInstructionGotoTable(const.METADATA_SERVICE_TABLE)]
        self.mod_flow(
            datapath=datapath,
            table_id=const.SERVICES_CLASSIFICATION_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            inst=inst)

    def _create_arp_responder(self, mac):
        self._arp_responder = ArpResponder(
            self.get_datapath(),
            None,
            METADATA_SERVICE_IP,
            mac
        )
        self._arp_responder.add()

    def _get_rewrite_ip_and_output_actions(self, ofproto, parser):
        """
        Retrieve the actions that rewrite the dst IP field with the in_port,
        set the first bit of that field, and output to the metadata service
        OVS port.
        """
        return [
            parser.NXActionRegMove(
                src_field='in_port',
                dst_field='ipv4_src',
                n_bits=32,
            ),
            parser.NXActionRegLoad(31, 1, 'ipv4_src', 1),
            parser.OFPActionOutput(
                self._ofport,
                ofproto.OFPCML_NO_BUFFER,
            )
        ]

    def _add_tap_metadata_port(self, ofport):
        """
        Add the flows that can be added with the current available information:
        Regular Client->Server packets have IP rewritten, and sent to OVS port
        TCP Syn packets are sent to controller, so that response flows can be
            added.
        Packets from the OVS port are detected and sent for classification.
        """
        self._ofport = ofport
        mac = self._get_tap_metadata_port_mac()
        datapath = self.get_datapath()
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        # Regular packet
        match = parser.OFPMatch(eth_type=ethernet.ether.ETH_TYPE_IP)
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS,
            self._get_rewrite_ip_and_output_actions(ofproto, parser),
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
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS,
            [
                parser.OFPActionOutput(
                    ofproto.OFPP_CONTROLLER,
                    ofproto.OFPCML_NO_BUFFER,
                )
            ],
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
        match = parser.OFPMatch(in_port=ofport)
        inst = [parser.OFPInstructionGotoTable(
            const.METADATA_SERVICE_REPLY_TABLE
        )]
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            inst=inst,
        )
        self._create_arp_responder(mac)

    def _get_tap_metadata_port_mac(self):
        cmd = ['ip', 'netns', 'exec', 'ns-metadata',
               'ip', 'link', 'show', 'dev', 'tap-metadata']
        output = utils.execute(cmd, run_as_root=True, check_exit_code=[0])
        output = output.split('\n')[1]
        regex = '^\s*link/ether\s*(([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})'
        match = re.search(regex, output)
        mac = match.group(1)
        assert mac, 'Failed to find mac for tap-metadata'
        return mac

    def ovs_sync_started(self):
        self.initialize()

    def initialize(self):
        self._add_incoming_flows()
        self.api.register_table_handler(const.METADATA_SERVICE_TABLE,
                self.packet_in_handler)
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
            'tap-metadata',
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
        self._add_tap_metadata_port(ofport)
        raise loopingcall.LoopingCallDone()

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)
        pkt_eth = pkt.get_protocol(ethernet.ethernet)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)
        if pkt_ip is None:
            # This can happen, since we only test for tcp, not ip
            LOG.error(_LE("No support for non IpV4 protocol"))
            return
        datapath = self.get_datapath()
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match.get('in_port')
        metadata = msg.match.get('metadata')
        ip = pkt_ip.src
        new_ip_bin = netaddr.IPAddress(in_port) | 0x80000000
        new_ip = str(new_ip_bin)
        self._add_flow_reset_ip_and_output(
            new_ip,
            ip,
            metadata,
            parser,
            ofproto,
        )
        self._add_arp_to_namespace(new_ip, pkt_eth.src)
        self._resume_packet(msg, ofproto, parser)

    def _add_flow_reset_ip_and_output(self, new_ip, old_ip, metadata,
            parser, ofproto):
        match = parser.OFPMatch(
            eth_type=ethernet.ether.ETH_TYPE_IP,
            ipv4_dst=new_ip,
        )
        actions = [
            parser.OFPActionSetField(ipv4_dst=old_ip),
            parser.OFPActionSetField(metadata=metadata),
        ]
        inst = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            parser.OFPInstructionGotoTable(const.L2_LOOKUP_TABLE),
        ]
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.METADATA_SERVICE_REPLY_TABLE,
            idle_timeout=FLOW_IDLE_TIMEOUT,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            inst=inst
        )

    def _add_arp_to_namespace(self, ip, mac):
        cmd = ['ip', 'netns', 'exec', 'ns-metadata', 'ip', 'neighbor',
               'replace', ip, 'lladdr', mac, 'dev', 'tap-metadata']
        utils.execute(cmd, run_as_root=True, check_exit_code=[0])

    def _resume_packet(self, msg, ofproto, parser):
        # NOTE(oanson) Newer ofproto versions take match, not just in_port
        #match = parser.OFPMatch(
            #in_port=msg.match.get("in_port"),
        #)
        actions = self._get_rewrite_ip_and_output_actions(ofproto, parser)
        datapath = self.get_datapath()
        out = datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            #match=match,
            in_port=msg.match.get("in_port"),
            actions=actions,
            data=msg.data)
        datapath.send_msg(out)


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
        connection_string = self._get_ovsdb_connection_string()
        self.ovsdb = ovsdb_vswitch_impl.DFConnection(
            connection_string,
            10,
            ovsdb_vswitch_impl.get_schema_helper(
                connection_string,
                tables={
                    'Interface': [
                        'ofport',
                        'external_ids',
                    ],
                },
            )
        )
        self.ovsdb.start()
        self.idl = self.ovsdb.idl
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
        in_port = int(netaddr.IPAddress(remote_addr) & ~0x80000000)
        headers = dict(req.headers)
        instance_id, tenant_id = self._get_instance_and_tenant_id(in_port)
        headers.update({
            'X-Forwarded-For': self._get_instance_link_local_ip(in_port),
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

    def _get_instance_link_local_ip(self, in_port):
        """
        Return some link-local IP address. Since the VM randomly chooses one
        without telling anyone, NOVA doesn't know the true IP anyway.
        """
        return '169.254.1.1'

    def _get_instance_and_tenant_id(self, in_port):
        self.idl.run()
        interface = idlutils.row_by_value(
            self.idl,
            'Interface',
            'ofport',
            [in_port],
        )
        external_ids = interface.external_ids
        instance_id = external_ids.get('vm-id', "")
        tenant_id = self._get_tenant_id(interface)
        return instance_id, tenant_id

    def _get_tenant_id(self, interface):
        external_ids = interface.external_ids
        lport_id = external_ids.get('iface-id', '')
        lport = self.nb_api.get_logical_port(lport_id)
        return lport.get_topic()

    # Taken from Neurton: neutron/agent/metadata/agent.py
    def _sign_instance_id(self, instance_id):
        secret = self.conf.metadata_proxy_shared_secret
        secret = encodeutils.to_utf8(secret)
        instance_id = encodeutils.to_utf8(instance_id)
        return hmac.new(secret, instance_id, hashlib.sha256).hexdigest()
