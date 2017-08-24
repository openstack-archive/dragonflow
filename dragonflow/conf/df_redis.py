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


from oslo_config import cfg

from dragonflow._i18n import _


df_redis_opts = [
    cfg.IntOpt(
        'retries',
        default=5,
        min=1,
        help=_('Amount of retries for each Redis operations. At least 2 in '
               'clustered Redis environments.'),
    ),
    cfg.IntOpt(
        'batch_amount',
        default=50,
        min=10,
        help=_('When performing batch operations using pipeline, send this '
               'amount of commands each round trip.'),
    ),
]


def register_opts():
    cfg.CONF.register_opts(df_redis_opts, group='df_redis')


def list_opts():
    return {'df_redis': df_redis_opts}
