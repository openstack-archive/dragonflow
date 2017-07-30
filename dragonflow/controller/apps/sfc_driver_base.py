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
import abc
from oslo_log import log
import six

LOG = log.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class SfcBaseDriver(object):
    def __init__(self, app):
        '''Initialization code

        :param app:    Instance of SFC app
        '''
        pass

    @abc.abstractmethod
    def install_encap_flows(self, port_chain, flow_classifier):
        '''Install flows that will capture packets classified by Flow
        Classifier app. The captured packets arrive at SFC_ENCAP_TABLE with
        reg6 set to unique key of the flow classifier. The function will be
        called only for flow classifiers whose is_classification_local is true.

        :param port_chain:       Relevant port chain
        :param flow_classifier:  Relevant flow classifier
        '''
        pass

    @abc.abstractmethod
    def uninstall_encap_flows(self, port_chain, flow_classifier):
        '''Reverse the installed flows of the above
        '''
        pass

    @abc.abstractmethod
    def install_decap_flows(self, port_chain, flow_classifier):
        '''Install flows thats that return packet to SFC_END_OF_CHAIN_TABLE
        once they are done traversing the service chain. Returning packets
        should have flow classifier's unique_key in reg6. This is called only
        for flow classifiers of the port chain

        :param port_chain:       Relevant port chain
        :param flow_classifier:  Relevant flow classifier
        '''
        pass

    @abc.abstractmethod
    def uninstall_decap_flows(self, port_chain, flow_classifier):
        '''Reverse the installed flows of the above
        '''
        pass

    @abc.abstractmethod
    def install_forward_to_dest(self, port_chain, flow_classifier):
        '''Install flows that forward packets to the destination node. When a
        packet finishes a chain, and its flow classifier does not dispatch
        locally, the packet is forwarded to the destination node before it is
        decapsulated. This function is responsible to install those flows.
        This function is called only for flow classifiers that have
        is_dispatch_local as false.

        :param port_chain:       Relevant port chain
        :param flow_classifier:  Relevant flow classifier
        '''
        pass

    @abc.abstractmethod
    def uninstall_forward_to_dest(self, port_chain, flow_classifier):
        '''Reverse the installed flows of the above
        '''
        pass

    @abc.abstractmethod
    def install_port_pair_group_flows(self, port_chain, port_pair_group):
        '''Install flows that forward a packet into all the port pairs of the
        provided port pair group.

        This is called for all port pair groups of the port chain

        :param port_chain:       Relevant port chain
        :param port_pair_group:  Relevant port pair group
        '''
        pass

    @abc.abstractmethod
    def uninstall_port_pair_group_flows(self, port_chain, port_pair_group):
        '''Reverse the installed flows of the above
        '''
        pass

    @abc.abstractmethod
    def install_port_pair_egress_flows(self, port_chain, port_pair_group,
                                       port_pair):
        '''Install flows that capture the packets coming out of the egress
        port of the provided port pair and forward them into flows
        that dispatch the next port pair group.

        This method is called for all port parts whose egress lport is local.

        :param port_chain:       Relevant port chain
        :param port_pair_group:  Relevant port pair group
        :param port_pair:        Relevant port pair
        '''
        pass

    @abc.abstractmethod
    def uninstall_port_pair_egress_flows(self, port_chain, port_pair_groups,
                                         port_pair):
        '''Reverse the installed flows of the above
        '''
        pass
