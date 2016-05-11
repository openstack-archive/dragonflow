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

import eventlet
eventlet.monkey_patch()

import inspect
import random

from sqlalchemy import func
from sqlalchemy.orm import exc as orm_exc

from dragonflow._i18n import _LI, _LW
from dragonflow.common import exceptions as df_exc
from dragonflow.db.neutron import models

from neutron.db import api as db_api

from oslo_config import cfg
from oslo_db import api as oslo_db_api
from oslo_db import exception as db_exc
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import timeutils
import six


# Used to identify each API session
LOCK_SEED = 9876543210

# Used to wait and retry for distributed lock
LOCK_MAX_RETRIES = 100
LOCK_INIT_RETRY_INTERVAL = 2
LOCK_MAX_RETRY_INTERVAL = 10

# global lock id
GLOBAL_LOCK_ID = "ffffffffffffffffffffffffffffffff"


LOG = log.getLogger(__name__)


class wrap_db_lock(object):

    def __init__(self):
        super(wrap_db_lock, self).__init__()

    def __call__(self, f):
        @six.wraps(f)
        def wrap_db_lock(*args, **kwargs):
            context = args[1]  # the neutron context object
            session_id = 0
            result = None

            # NOTE(nick-ma-z): In some admin operations in Neutron,
            # the project_id is set to None, so we set it to a global
            # lock id.
            lock_id = context.project_id
            if not lock_id:
                lock_id = GLOBAL_LOCK_ID

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


@oslo_db_api.wrap_db_retry(max_retries=LOCK_MAX_RETRIES,
                           retry_interval=LOCK_INIT_RETRY_INTERVAL,
                           inc_retry_interval=True,
                           max_retry_interval=LOCK_MAX_RETRY_INTERVAL,
                           retry_on_deadlock=True,
                           retry_on_request=True)
def _acquire_lock(oid):
    # generate temporary session id for this API context
    sid = _generate_session_id()

    # NOTE(nick-ma-z): we disallow subtransactions because the
    # retry logic will bust any parent transactions
    session = db_api.get_session()
    with session.begin():
        LOG.info(_LI("Try to get lock for object %(oid)s in "
                     "session %(sid)s."), {'oid': oid, 'sid': sid})
        _lock_free_update(session, oid, False, sid)
        LOG.info(_LI("Lock is acquired for object %(oid)s in "
                     "session %(sid)s."), {'oid': oid, 'sid': sid})
        return sid


@oslo_db_api.wrap_db_retry(max_retries=LOCK_MAX_RETRIES,
                           retry_interval=LOCK_INIT_RETRY_INTERVAL,
                           inc_retry_interval=True,
                           max_retry_interval=LOCK_MAX_RETRY_INTERVAL,
                           retry_on_deadlock=True,
                           retry_on_request=True)
def _release_lock(oid, sid):
    # NOTE(nick-ma-z): we disallow subtransactions because the
    # retry logic will bust any parent transactions
    session = db_api.get_session()
    with session.begin():
        LOG.info(_LI("Try to get lock for object %(oid)s in "
                     "session %(sid)s."), {'oid': oid, 'sid': sid})
        _lock_free_update(session, oid, True, sid)
        LOG.info(_LI("Lock is released for object %(oid)s in "
                     "session %(sid)s."), {'oid': oid, 'sid': sid})


def _generate_session_id():
    return random.randint(0, LOCK_SEED)


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
                _update_lock(session, row, False, 0)
    except orm_exc.NoResultFound:
        try:
            session = db_api.get_session()
            with session.begin():
                _create_db_row(session, oid=id)
        except db_exc.DBDuplicateEntry:
            # the lock is concurrently created.
            pass


def _lock_free_update(session, id, state, session_id):
    if not state:
        # acquire lock
        params = {'lock': not state, 'session_id': session_id,
                  'created_at': func.now()}
        rows_update = session.query(models.DFLockedObjects).\
            filter_by(object_uuid=id).\
            filter_by(lock=state).\
            update(params, synchronize_session='fetch')
    else:
        # release lock
        params = {'lock': not state, 'session_id': 0}
        rows_update = session.query(models.DFLockedObjects).\
            filter_by(object_uuid=id).\
            filter_by(lock=state).\
            filter_by(session_id=session_id).\
            update(params, synchronize_session='fetch')

    if not rows_update:
        LOG.info(_LI('The lock for object %(id)s in session '
                     '%(sid)s cannot be updated.'), {'id': id,
                                                     'sid': session_id})
        raise db_exc.RetryRequest(df_exc.DBLockFailed(oid=id, sid=session_id))


def _update_lock(session, row, lock, session_id):
    row.lock = lock
    row.session_id = session_id

    # NOTE(nick-ma-z): created_at means the time when the lock is acquired.
    if session_id:
        row.created_at = func.now()

    session.merge(row)
    session.flush()


def _create_db_row(session, oid):
    row = models.DFLockedObjects(object_uuid=oid,
                                 lock=False, session_id=0,
                                 created_at=func.now())
    session.add(row)
    session.flush()
