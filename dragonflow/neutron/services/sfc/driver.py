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

from networking_sfc.services.sfc.drivers import base

from dragonflow.db.models import sfc
from dragonflow.neutron.services import mixins


def _get_optional_params(obj, *params):
    '''This function returns a dictionary with all the parameters from `params`
    that were present in `obj`, for example:


    >>> _get_optional_params({'a': 1, 'b': 2}, 'a', 'c')
    {'a': 1}
    '''

    res = {}
    for param in params:
        if param in obj:
            res[param] = obj.get(param)
    return res


class DfSfcDriver(base.SfcDriverBase, mixins.LazyNbApiMixin):
    # The new SFC driver API:
    def initialize(self):
        pass

    def create_port_chain_postcommit(self, context):
        port_chain = context.current
        pc_params = port_chain.get('chain_parameters')

        self.nb_api.create(
            sfc.PortChain(
                id=port_chain['id'],
                topic=port_chain['project_id'],
                name=port_chain.get('name'),
                port_pair_groups=port_chain.get('port_pair_groups', []),
                flow_classifiers=port_chain.get('flow_classifiers', []),
                protocol=pc_params.get('correlation'),
                chain_id=port_chain.get('chain_id'),
            ),
        )

    def update_port_chain_postcommit(self, context):
        port_chain = context.current
        extra_args = _get_optional_params(
            port_chain,
            'port_pair_groups',
            'flow_classifiers',
        )

        self.nb_api.update(
            sfc.PortChain(
                id=port_chain['id'],
                topic=port_chain['project_id'],
                name=port_chain.get('name'),
                **extra_args
            ),
        )

    def delete_port_chain_postcommit(self, context):
        port_chain = context.current

        self.nb_api.delete(
            sfc.PortChain(
                id=port_chain['id'],
                topic=port_chain['project_id'],
            ),
        )

    def create_port_pair_group_postcommit(self, context):
        port_pair_group = context.current

        self.nb_api.create(
            sfc.PortPairGroup(
                id=port_pair_group['id'],
                topic=port_pair_group['project_id'],
                name=port_pair_group.get('name'),
                port_pairs=port_pair_group.get('port_pairs', []),
                # FIXME (dimak) add support for lb_fields, service_type
            ),
        )

    def update_port_pair_group_postcommit(self, context):
        port_pair_group = context.current
        extra_args = _get_optional_params(port_pair_group, 'port_pairs')

        self.nb_api.update(
            sfc.PortPairGroup(
                id=port_pair_group['id'],
                topic=port_pair_group['project_id'],
                name=port_pair_group.get('name'),
                **extra_args
            ),
        )

    def delete_port_pair_group_postcommit(self, context):
        port_pair_group = context.current
        self.nb_api.delete(
            sfc.PortPairGroup(
                id=port_pair_group['id'],
                topic=port_pair_group['project_id'],
            ),
        )

    def create_port_pair_postcommit(self, context):
        port_pair = context.current
        sf_params = port_pair.get('service_function_parameters', {})

        self.nb_api.create(
            sfc.PortPair(
                id=port_pair['id'],
                topic=port_pair['project_id'],
                name=port_pair.get('name'),
                ingress_port=port_pair['ingress'],
                egress_port=port_pair['egress'],
                correlation_mechanism=(
                    sf_params.get('correlation') or sfc.CORR_NONE
                ),
                weight=sf_params.get('weight')
            ),
        )

    def update_port_pair_postcommit(self, context):
        port_pair = context.current

        self.nb_api.update(
            sfc.PortPair(
                id=port_pair['id'],
                topic=port_pair['project_id'],
                name=port_pair.get('name'),
            ),
        )

    def delete_port_pair_postcommit(self, context):
        port_pair = context.current

        self.nb_api.delete(
            sfc.PortPair(
                id=port_pair['id'],
                topic=port_pair['project_id'],
            ),
        )

    # Legacy SFC driver API, has to be stubbed due to ABC
    def create_port_chain(self, context):
        pass

    def update_port_chain(self, context):
        pass

    def delete_port_chain(self, context):
        pass

    def create_port_pair_group(self, context):
        pass

    def update_port_pair_group(self, context):
        pass

    def delete_port_pair_group(self, context):
        pass

    def create_port_pair(self, context):
        pass

    def update_port_pair(self, context):
        pass

    def delete_port_pair(self, context):
        pass
