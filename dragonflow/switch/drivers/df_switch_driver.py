# Copyright (c) 2018 OpenStack Foundation
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


import abc
import six


@six.add_metaclass(abc.ABCMeta)
class DfSwitchDriver(object):
    def __init__(self, nb_api):
        super(DfSwitchDriver, self).__init__()
        self.db_change_callback = None
        self.nb_api = nb_api

    def initialize(self, db_change_callback):
        self.db_change_callback = db_change_callback

    @abc.abstractmethod
    def start(self):
        """Start running the switch backend"""

    @abc.abstractmethod
    def stop(self):
        """Stop the switch backend"""

    @abc.abstractmethod
    def switch_sync_started(self):
        """Callback on switch sync start"""

    @abc.abstractmethod
    def switch_sync_finished(self):
        """Callback on switch sync done"""

    def sync_ignore_models(self):
        """Which models to ignore on sync
        :returns list of model names
        """
        return []
