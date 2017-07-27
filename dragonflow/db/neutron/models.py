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

from neutron_lib.db import model_base
import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import expression
from sqlalchemy import types


class utc_timestamp(expression.FunctionElement):
    type = types.DateTime()


@compiles(utc_timestamp, 'postgresql')
def pg_utc_timestamp(element, compiler, **kw):
    return "TIMEZONE('utc', CURRENT_TIMESTAMP)"


@compiles(utc_timestamp, 'mssql')
def ms_utc_timestamp(element, compiler, **kw):
    return "GETUTCDATE()"


@compiles(utc_timestamp, 'mysql')
def my_utc_timestamp(element, compiler, **kw):
    return "UTC_TIMESTAMP()"


class DFLockedObjects(model_base.BASEV2):
    __tablename__ = 'dflockedobjects'

    object_uuid = sa.Column(sa.String(36), primary_key=True)
    lock = sa.Column(sa.Boolean, default=False)
    session_id = sa.Column(sa.BigInteger, default=0)
    created_at = sa.Column(sa.DateTime, onupdate=utc_timestamp())
