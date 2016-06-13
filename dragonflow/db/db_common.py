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

from oslo_utils import timeutils

SEND_ALL_TOPIC = b'D'
DB_SYNC_MINIMUM_INTERVAL = 180


class DbUpdate(object):
    """Encapsulates a DB update

    An instance of this object carries the information necessary to prioritize
    and process a request to update a DB entry.
    Lower value is higher priority !
    """
    def __init__(self, table, key, action, value, priority=5,
                 timestamp=None, topic=SEND_ALL_TOPIC):
        self.priority = priority
        self.timestamp = timestamp
        if not timestamp:
            self.timestamp = timeutils.utcnow()
        self.key = key
        self.action = action
        self.table = table
        self.value = value
        self.topic = topic

    def to_dict(self):
        update = {
                'table': self.table,
                'key': self.key,
                'action': self.action,
                'value': self.value,
                'topic': self.topic
        }
        return update

    def __str__(self):
        return "Action:%s, Table:%s, Key:%s Value:%s Topic:%s" % (
            self.action,
            self.table,
            self.key,
            self.value,
            self.topic,
        )

    def __lt__(self, other):
        """Implements priority among updates

        Lower numerical priority always gets precedence. When comparing two
        updates of the same priority then the one with the earlier timestamp
        gets procedence.  In the unlikely event that the timestamps are also
        equal it falls back to a simple comparison of ids meaning the
        precedence is essentially random.
        """
        if self.priority != other.priority:
            return self.priority < other.priority
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        return self.key < other.key
