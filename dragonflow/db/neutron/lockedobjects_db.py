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

import contextlib
import functools
import inspect
import random

from neutron.db import api as db_api
from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_log import log
from oslo_utils import timeutils
import six
from sqlalchemy.orm import exc as orm_exc

from dragonflow.common import exceptions as df_exc
from dragonflow.db.neutron import models

# Used to identify each API session
LOCK_SEED = 9876543210

# Used to wait and retry for distributed lock
LOCK_MAX_RETRIES = 500
LOCK_INIT_RETRY_INTERVAL = 0.1
LOCK_MAX_RETRY_INTERVAL = 1

LOG = log.getLogger(__name__)


def get_lock_id_from_context_project_id(self, context, *args, **kwargs):
    return context.project_id


def get_lock_id_from_context_current_id(self, context, *args, **kwargs):
    return context.current['id']


def get_lock_id_from_context_current_network_id(self,
                                                context, *args, **kwargs):
    return context.current['network_id']


def get_lock_id_from_argument(index, self, *args, **kwargs):
    return args[index]


get_lock_id_from_2nd_argument = functools.partial(get_lock_id_from_argument, 1)


def get_lock_id_from_security_group_id(self, *args, **kwargs):
    return kwargs['security_group_id']


def get_lock_id_from_security_group_object(self, *args, **kwargs):
    return kwargs['security_group']['id']


def get_lock_id_from_security_group_rule_parent(self, *args, **kwargs):
    return kwargs['security_group_rule']['security_group_id']


def get_lock_id_for_qos_policy(self, context, policy, *args, **kwargs):
    return policy['id']


def get_lock_id_from_host_argument(self, host, *args, **kwargs):
    return host[:35]


class wrap_db_lock(object):
    def __init__(self, getter):
        super(wrap_db_lock, self).__init__()
        self.getter = getter

    def is_within_wrapper(self):
            # magic to prevent from nested lock
            for frame in inspect.stack()[1:]:
                if frame[3] == 'wrap_db_lock':
                    return True
            return False

    @contextlib.contextmanager
    def lock(self, lock_id):
        within_wrapper = self.is_within_wrapper()
        if not within_wrapper:
            # test and create the lock if necessary
            _test_and_create_object(lock_id)
            session_id = _acquire_lock(lock_id)

        try:
            # Code in context may throw exception,
            # but we still need cleanup
            yield
        finally:
            if not within_wrapper:
                try:
                    _release_lock(lock_id, session_id)
                except Exception as e:
                    LOG.exception(e)

    def __call__(self, f):
        @six.wraps(f)
        def wrap_db_lock(*args, **kwargs):
            lock_id = self.getter(*args, **kwargs)
            with self.lock(lock_id):
                return f(*args, **kwargs)
        return wrap_db_lock


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
    session = db_api.get_writer_session()
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
    session = db_api.get_writer_session()
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
def _test_and_create_object(uuid):
    try:
        session = db_api.get_writer_session()
        with session.begin():
            row = session.query(models.DFLockedObjects).filter_by(
                object_uuid=uuid).one()
            # test ttl
            if row.lock and timeutils.is_older_than(
                    row.created_at, cfg.CONF.df.distributed_lock_ttl):
                # reset the lock if it is timeout
                LOG.warning('The lock for object %(id)s is reset '
                            'due to timeout.', {'id': uuid})
                _lock_free_update(session, uuid, lock_state=True,
                                  session_id=row.session_id)
    except orm_exc.NoResultFound:
        try:
            session = db_api.get_writer_session()
            with session.begin():
                _create_db_row(session, oid=uuid)
        except db_exc.DBDuplicateEntry:
            # the lock is concurrently created.
            pass


def _lock_free_update(session, uuid, lock_state=False, session_id=0):
    """Implement lock-free atomic update for the distributed lock

    :param session:    the db session
    :type session:     DB Session object
    :param uuid:         the lock uuid
    :type uuid:          string
    :param lock_state: the lock state to update
    :type lock_state:  boolean
    :param session_id: the API session ID to update
    :type session_id:  string
    :raises RetryRequest(): when the lock failed to update
    """
    if not lock_state:
        # acquire lock
        search_params = {'object_uuid': uuid, 'lock': lock_state}
        update_params = {'lock': not lock_state, 'session_id': session_id}
    else:
        # release or reset lock
        search_params = {'object_uuid': uuid, 'lock': lock_state,
                         'session_id': session_id}
        update_params = {'lock': not lock_state, 'session_id': 0}

    rows_update = session.query(models.DFLockedObjects).\
        filter_by(**search_params).\
        update(update_params, synchronize_session='fetch')

    if not rows_update:
        LOG.debug('The lock for object %(id)s in session '
                  '%(sid)s cannot be updated.', {'id': uuid,
                                                 'sid': session_id})
        raise db_exc.RetryRequest(df_exc.DBLockFailed(oid=uuid,
                                                      sid=session_id))


def _create_db_row(session, oid):
    row = models.DFLockedObjects(object_uuid=oid,
                                 lock=False, session_id=0)
    session.add(row)
    session.flush()
