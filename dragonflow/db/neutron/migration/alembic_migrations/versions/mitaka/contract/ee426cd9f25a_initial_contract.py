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

"""Start of df contract branch

Revision ID: ee426cd9f25a
Revises: ce93d45fd192
Create Date: 2016-02-01 11:27:49.306394

"""

from neutron.db.migration import cli


# revision identifiers, used by Alembic.
revision = 'ee426cd9f25a'
down_revision = 'ce93d45fd192'
branch_labels = (cli.CONTRACT_BRANCH,)


def upgrade():
    pass
