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

import random
import time

from sqlalchemy import func
from sqlalchemy.orm import exc as orm_exc

from dragonflow._i18n import _LI
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db.neutron import models

from neutron.db import api as db_api

from oslo_db import api as oslo_db_api
from oslo_log import log


LOCK_MAX_RETRIES = 10
WAIT_SECONDS = 1
LOCK_SEED = 9876543210


LOG = log.getLogger(__name__)


class DFDBLock(object):
    def __init__(self, context, id):
        self.context = context
        self.id = id

    def __enter__(self):
        self.session_id = _acquire_lock(self.context, self.id)

    def __exit__(self, type, value, traceback):
        _release_lock(self.context, self.id, self.session_id)


def create_lock(context, oid):
    try:
        with db_api.autonested_transaction(context.session):
            _create_db_row(context.session, oid=oid)
    except orm_exc.MultipleResultsFound:
        pass


def delete_lock(context, oid):
    with db_api.autonested_transaction(context.session):
        _delete_db_row(context.session, oid=oid)


def _acquire_lock(context, oid):
    max_tries = LOCK_MAX_RETRIES
    sid = _generate_session_id()
    while(max_tries > 0):
        try:
            with db_api.autonested_transaction(context.session):
                LOG.info(_LI("Try to get lock for object %(oid)s in "
                             "session %(sid)s."), {'oid': oid, 'sid': sid})
                row = _get_object_with_lock(context.session, oid, False)
                _update_lock(context.session, row, True, oid, session_id=sid)
            LOG.info(_LI("Lock is acquired for object %(oid)s in "
                         "session %(sid)s."), {'oid': oid, 'sid': sid})
            return sid
        except Exception as e:
            time.sleep(WAIT_SECONDS)
            max_tries = max_tries - 1
            LOG.warning(e)
    raise df_exceptions.DBDeadLockException(id=oid)


def _release_lock(context, oid, sid):
    max_tries = LOCK_MAX_RETRIES
    while(max_tries > 0):
        try:
            with db_api.autonested_transaction(context.session):
                LOG.info(_LI("Try to get lock for object %(oid)s in "
                             "session %(sid)s."), {'oid': oid, 'sid': sid})
                row = _get_object_with_lock(context.session, oid, True,
                                            session_id=sid)
                _update_lock(context.session, row, False, oid, session_id=0)
            LOG.info(_LI("Lock is released for object %(oid)s in "
                         "session %(sid)s."), {'oid': oid, 'sid': sid})
            return
        except Exception as e:
            time.sleep(WAIT_SECONDS)
            max_tries = max_tries - 1
            LOG.warning(e)
    raise df_exceptions.DBDeadLockException(id=oid)


def _generate_session_id():
    return random.randint(0, LOCK_SEED)


def _get_all_db_rows(session):
    return session.query(models.DFLockedObjects).all()


def _get_object_with_lock(session, id, state, session_id=None):
    if session_id:
        return session.query(models.DFLockedObjects).filter_by(
            object_uuid=id,
            lock=state,
            session_id=session_id).with_for_update().first()
    else:
        return session.query(models.DFLockedObjects).filter_by(
            object_uuid=id, lock=state).with_for_update().first()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _update_lock(session, row, lock, oid, session_id):
    row.lock = lock
    row.session_id = session_id
    session.merge(row)
    session.flush()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _delete_db_row(session, row=None, oid=None):
    if oid:
        row = session.query(models.DFLockedObjects).filter_by(
            object_uuid=oid).one()
    if row:
        session.delete(row)
        session.flush()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _create_db_row(session, oid):
    row = models.DFLockedObjects(object_uuid=oid,
                                 lock=False, session_id=0,
                                 created_at=func.now())
    session.add(row)
    session.flush()
