# Copyright (c) 2015 OpenStack Foundation
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
#

"""Dragonflow versioned objects
Revision ID: f03c862d2645
Revises: 1dee3dc24674
Create Date: 2016-02-18 10:09:29.112343
"""

# revision identifiers, used by Alembic.
revision = 'f03c862d2645'
down_revision = '1dee3dc24674'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'dflockedobjects',
        sa.Column('object_uuid', sa.String(36), primary_key=True),
        sa.Column('lock', sa.Boolean, default=False),
        sa.Column('session_id', sa.BigInteger, default=0),
        sa.Column('created_at', sa.DateTime)
    )
