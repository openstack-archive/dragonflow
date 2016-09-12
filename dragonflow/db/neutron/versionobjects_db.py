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

from oslo_db import exception as db_exc
from oslo_log import log
from sqlalchemy.orm import exc as orm_exc

from dragonflow._i18n import _LW
from dragonflow.db.neutron import models

import sys

LOG = log.getLogger(__name__)


def _create_db_version_row(session, obj_id):
    try:
        row = models.DFVersionObjects(object_uuid=obj_id,
                                      version=0)
        session.add(row)
        session.flush()
        return 0
    except db_exc.DBDuplicateEntry:
        LOG.warning(_LW('DuplicateEntry in Neutron DB when'
                        'create version for object_id:%(id)s'), {'id': obj_id})
        return 0


def _update_db_version_row(session, obj_id):
    try:
        row = session.query(models.DFVersionObjects).filter_by(
                object_uuid=obj_id).one()
        new_version = row.version + 1
        if new_version == sys.maxsize:
            new_version = 0
        row.version = new_version
        session.merge(row)
        session.flush()
        return new_version
    except orm_exc.NoResultFound:
        LOG.warning(_LW('NoResultFound in Neutron DB when'
                        'update version for object_id:%(id)s'), {'id': obj_id})
        return _create_db_version_row(session, obj_id)


def _delete_db_version_row(session, obj_id):
    try:
        row = session.query(models.DFVersionObjects).filter_by(
                object_uuid=obj_id).one()
        session.delete(row)
        session.flush()
    except orm_exc.NoResultFound:
        pass
