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

from sqlalchemy.orm import exc as orm_exc
from dragonflow.db.neutron import models

from oslo_db import exception as db_exc


def _create_db_version_row(session, obj_id):
    try:
        row = models.DFVersionObjects(object_uuid=obj_id,
                                      version=0)
        session.add(row)
        session.flush()
        return 0
    except db_exc.DBDuplicateEntry:
        return 0


def _update_db_version_row(session, obj_id):
    try:
        row = session.query(models.DFVersionObjects).filter_by(
                object_uuid=obj_id).one()
        new_version = row.version + 1
        row = models.DFVersionObjects(object_uuid=obj_id,
                                      version=new_version)
        session.merge(row)
        session.flush()
        return new_version
    except orm_exc.NoResultFound:
        try:
            _create_db_version_row(session, obj_id)
        except db_exc.DBDuplicateEntry:
            return 0


def _delete_db_version_row(session, obj_id):
    try:
        row = session.query(models.DFVersionObjects).filter_by(
                object_uuid=obj_id).one()
        session.delete(row)
        session.flush()
    except orm_exc.NoResultFound:
        pass
