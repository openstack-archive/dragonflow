# Copyright (c) 2015 OpenStack Foundation
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

import inspect
import random

from neutron.db import api as db_api
from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import timeutils
import six
from sqlalchemy.orm import exc as orm_exc

from dragonflow._i18n import _LW
from dragonflow.common import exceptions as df_exc
from dragonflow.db.neutron import models

# Used to identify each API session
LOCK_SEED = 9876543210

# Used to wait and retry for distributed lock
LOCK_MAX_RETRIES = 500
LOCK_INIT_RETRY_INTERVAL = 0.1
LOCK_MAX_RETRY_INTERVAL = 1

# The resource need to be protected by lock
RESOURCE_DF_PLUGIN = 1
RESOURCE_ML2_NETWORK_OR_PORT = 2
RESOURCE_ML2_SUBNET = 3
RESOURCE_ML2_SECURITY_GROUP = 4
RESOURCE_ML2_SECURITY_GROUP_RULE_CREATE = 5
RESOURCE_ML2_SECURITY_GROUP_RULE_DELETE = 6
RESOURCE_FIP_UPDATE_OR_DELETE = 7
RESOURCE_ROUTER_UPDATE_OR_DELETE = 8
RESOURCE_QOS = 9


LOG = log.getLogger(__name__)


class wrap_db_lock(object):

    def __init__(self, type):
        super(wrap_db_lock, self).__init__()
        self.type = type

    def __call__(self, f):
        @six.wraps(f)
        def wrap_db_lock(*args, **kwargs):
            session_id = 0
            result = None

            # NOTE(nick-ma-z): In some admin operations in Neutron,
            # the project_id is set to None, so we set it to a global
            # lock id.
            lock_id = _get_lock_id_by_resource_type(self.type, args, kwargs)

            # magic to prevent from nested lock
            within_wrapper = False
            for frame in inspect.stack()[1:]:
                if frame[3] == 'wrap_db_lock':
                    within_wrapper = True
                    break

            if not within_wrapper:
                # test and create the lock if necessary
                _test_and_create_object(lock_id)
                session_id = _acquire_lock(lock_id)

            try:
                result = f(*args, **kwargs)
            except Exception as e:
                with excutils.save_and_reraise_exception() as ctxt:
                    ctxt.reraise = True
            finally:
                if not within_wrapper:
                    try:
                        _release_lock(lock_id, session_id)
                    except Exception as e:
                        LOG.exception(e)

            return result
        return wrap_db_lock


def _get_lock_id_by_resource_type(resource_type, *args, **kwargs):
    if RESOURCE_DF_PLUGIN == resource_type:
        lock_id = args[0][1].project_id
    elif RESOURCE_ML2_NETWORK_OR_PORT == resource_type:
        lock_id = args[0][1].current['id']
    elif RESOURCE_ML2_SUBNET == resource_type:
        lock_id = args[0][1].current['network_id']
    elif RESOURCE_FIP_UPDATE_OR_DELETE == resource_type:
        lock_id = args[0][2]
    elif RESOURCE_ROUTER_UPDATE_OR_DELETE == resource_type:
        lock_id = args[0][2]
    elif RESOURCE_ML2_SECURITY_GROUP == resource_type:
        lock_id = args[1]['security_group']['id']
    elif RESOURCE_ML2_SECURITY_GROUP_RULE_CREATE == resource_type:
        lock_id = args[1]['security_group_rule']['security_group_id']
    elif RESOURCE_ML2_SECURITY_GROUP_RULE_DELETE == resource_type:
        lock_id = args[1]['security_group_id']
    elif RESOURCE_QOS == resource_type:
        lock_id = args[0][2]['id']
    else:
        raise df_exc.UnknownResourceException(resource_type=resource_type)

    return lock_id


@oslo_db_api.wrap_db_retry(max_retries=LOCK_MAX_RETRIES,
                           retry_interval=LOCK_INIT_RETRY_INTERVAL,
                           inc_retry_interval=True,
                           max_retry_interval=LOCK_MAX_RETRY_INTERVAL,
                           retry_on_deadlock=True)
def _acquire_lock(oid):
    # generate temporary session id for this API context
    sid = _generate_session_id()

    # NOTE(nick-ma-z): we disallow subtransactions because the
    # retry logic will bust any parent transactions
    session = db_api.get_session()
    with session.begin():
        LOG.debug("Try to get lock for object %(oid)s in "
                  "session %(sid)s.", {'oid': oid, 'sid': sid})
        _lock_free_update(session, oid, lock_state=False, session_id=sid)
        LOG.debug("Lock is acquired for object %(oid)s in "
                  "session %(sid)s.", {'oid': oid, 'sid': sid})
        return sid


@oslo_db_api.wrap_db_retry(max_retries=LOCK_MAX_RETRIES,
                           retry_interval=LOCK_INIT_RETRY_INTERVAL,
                           inc_retry_interval=True,
                           max_retry_interval=LOCK_MAX_RETRY_INTERVAL,
                           retry_on_deadlock=True)
def _release_lock(oid, sid):
    # NOTE(nick-ma-z): we disallow subtransactions because the
    # retry logic will bust any parent transactions
    session = db_api.get_session()
    with session.begin():
        LOG.debug("Try to release lock for object %(oid)s in "
                  "session %(sid)s.", {'oid': oid, 'sid': sid})
        _lock_free_update(session, oid, lock_state=True, session_id=sid)
        LOG.debug("Lock is released for object %(oid)s in "
                  "session %(sid)s.", {'oid': oid, 'sid': sid})


def _generate_session_id():
    return random.randint(0, LOCK_SEED)


@oslo_db_api.wrap_db_retry(max_retries=LOCK_MAX_RETRIES,
                           retry_interval=LOCK_INIT_RETRY_INTERVAL,
                           inc_retry_interval=True,
                           max_retry_interval=LOCK_MAX_RETRY_INTERVAL,
                           retry_on_deadlock=True)
def _test_and_create_object(id):
    try:
        session = db_api.get_session()
        with session.begin():
            row = session.query(models.DFLockedObjects).filter_by(
                object_uuid=id).one()
            # test ttl
            if row.lock and timeutils.is_older_than(row.created_at,
                                       cfg.CONF.df.distributed_lock_ttl):
                # reset the lock if it is timeout
                LOG.warning(_LW('The lock for object %(id)s is reset '
                                'due to timeout.'), {'id': id})
                _lock_free_update(session, id, lock_state=True,
                                  session_id=row.session_id)
    except orm_exc.NoResultFound:
        try:
            session = db_api.get_session()
            with session.begin():
                _create_db_row(session, oid=id)
        except db_exc.DBDuplicateEntry:
            # the lock is concurrently created.
            pass


def _lock_free_update(session, id, lock_state=False, session_id=0):
    """Implement lock-free atomic update for the distributed lock

    :param session:    the db session
    :type session:     DB Session object
    :param id:         the lock uuid
    :type id:          string
    :param lock_state: the lock state to update
    :type lock_state:  boolean
    :param session_id: the API session ID to update
    :type session_id:  string
    :raises:           RetryRequest() when the lock failed to update
    """
    if not lock_state:
        # acquire lock
        search_params = {'object_uuid': id, 'lock': lock_state}
        update_params = {'lock': not lock_state, 'session_id': session_id}
    else:
        # release or reset lock
        search_params = {'object_uuid': id, 'lock': lock_state,
                         'session_id': session_id}
        update_params = {'lock': not lock_state, 'session_id': 0}

    rows_update = session.query(models.DFLockedObjects).\
        filter_by(**search_params).\
        update(update_params, synchronize_session='fetch')

    if not rows_update:
        LOG.debug('The lock for object %(id)s in session '
                  '%(sid)s cannot be updated.', {'id': id,
                                                 'sid': session_id})
        raise db_exc.RetryRequest(df_exc.DBLockFailed(oid=id, sid=session_id))


def _create_db_row(session, oid):
    row = models.DFLockedObjects(object_uuid=oid,
                                 lock=False, session_id=0)
    session.add(row)
    session.flush()
