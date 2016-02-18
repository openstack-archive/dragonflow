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

from sqlalchemy import func
from sqlalchemy.orm import exc as sa_exc

from dragonflow.db.neutron import models

from neutron.db import api as db_api

from oslo_db import api as oslo_db_api


def increment_version(context, oid):
    try:
        with db_api.autonested_transaction(context.session):
            version_obj = _get_object_with_lock(context.session, oid)
            old_version = version_obj.version
            _increment_version(context.session, version_obj)
            return old_version
    except sa_exc.NoResultFound:
        return None


def delete_version(context, oid):
    try:
        with db_api.autonested_transaction(context.session):
            _delete_db_row(context.session, oid=oid)
    except sa_exc.NoResultFound:
        pass


def create_version(context, oid, otype):
    try:
        with db_api.autonested_transaction(context.session):
            _create_db_row(context.session, oid, otype)
    except sa_exc.MultipleResultsFound:
        pass


def _get_all_db_rows(session):
    return session.query(models.DFVersionedObjects).all()


def _get_object_with_lock(session, id):
    return session.query(models.DFVersionedObjects).filter_by(
        object_uuid=id).with_for_update().first()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _increment_version(session, row):
    row.version = row.version + 1
    session.merge(row)
    session.flush()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _delete_db_row(session, row=None, oid=None):
    if oid:
        row = session.query(models.DFVersionedObjects).filter_by(
            object_uuid=oid).one()
    if row:
        session.delete(row)
        session.flush()


@oslo_db_api.wrap_db_retry(max_retries=db_api.MAX_RETRIES,
                           retry_on_request=True)
def _create_db_row(session, object_uuid, object_type):
    row = models.DFVersionedObjects(object_uuid=object_uuid,
                                    object_type=object_type,
                                    version=0,
                                    created_at=func.now())
    session.add(row)
    session.flush()
