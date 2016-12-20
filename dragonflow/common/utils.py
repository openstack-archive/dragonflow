# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import time

import collections
import eventlet
import greenlet
from neutron_lib import constants as n_const
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import reflection
import six
from stevedore import driver

from dragonflow._i18n import _, _LE

DF_PUBSUB_DRIVER_NAMESPACE = 'dragonflow.pubsub_driver'
DF_NB_DB_DRIVER_NAMESPACE = 'dragonflow.nb_db_driver'
DF_PORT_STATUS_DRIVER_NAMESPACE = 'dragonflow.port_status_driver'
LOG = logging.getLogger(__name__)


def get_vhu_sockpath(sock_dir, port_id):
    # Frame the socket path of a virtio socket
    return os.path.join(
        sock_dir,
        # this parameter will become the virtio port name,
        # so it should not exceed IFNAMSIZ(16).
        (n_const.VHOST_USER_DEVICE_PREFIX + port_id)[:14])


def is_valid_version(old_obj, new_obj):
    if not old_obj:
        return True

    if new_obj.get('version') > old_obj.get('version'):
        return True
    elif new_obj.get('version') == old_obj.get('version'):
        return False
    else:
        LOG.debug("new_obj has an old version, new_obj: %s, old_obj: %s",
                  new_obj, old_obj)
        return False


def load_driver(driver_cfg, namespace):
    try:
        # Try to resolve by alias
        mgr = driver.DriverManager(namespace, driver_cfg)
        class_to_load = mgr.driver
    except RuntimeError:
        e1_info = sys.exc_info()
        # try with name
        try:
            class_to_load = importutils.import_class(driver_cfg)
        except (ImportError, ValueError):
            LOG.error(_LE("Error loading class %(class)s by alias e: %(e)s")
                    % {'class': driver_cfg, 'e': e1_info},
                    exc_info=e1_info)
            LOG.error(_LE("Error loading class by class name"),
                      exc_info=True)
            raise ImportError(_("Class not found."))
    return class_to_load()


class DFDaemon(object):

    def __init__(self, is_not_light=False):
        super(DFDaemon, self).__init__()
        self.pool = eventlet.GreenPool()
        self.is_daemonize = False
        self.thread = None
        self.is_not_light = is_not_light

    def daemonize(self, run):
        if self.is_daemonize:
            LOG.error(_LE("already daemonized"))
            return
        self.is_daemonize = True
        if self.is_not_light:
            self.thread = self.pool.spawn(run)
        else:
            self.thread = self.pool.spawn_n(run)
        eventlet.sleep(0)
        return self.thread

    def stop(self):
        if self.is_daemonize and self.thread:
            eventlet.greenthread.kill(self.thread)
            eventlet.sleep(0)
            self.thread = None
            self.is_daemonize = False

    def wait(self, timeout=None, exception=None):
        if not self.is_daemonize or not self.thread:
            return False
        if timeout and timeout > 0:
            timeout_obj = eventlet.Timeout(timeout, exception)
        try:
            self.thread.wait()
        except greenlet.GreenletExit:
            return True  # Good news
        finally:
            if timeout_obj:
                timeout_obj.cancel()


class wrap_func_retry(object):
    """Retry methods, if _errors raised

    Retry decorated methods. This decorator catches _errors
    and retries function in a loop until it succeeds, or until maximum
    retries count will be reached.

    Keyword arguments:

    :param retry_interval: seconds between operation retries
    :type retry_interval: int

    :param max_retries: max number of retries before an error is raised
    :type max_retries: int

    :param inc_retry_interval: determine increase retry interval or not
    :type inc_retry_interval: bool

    :param max_retry_interval: max interval value between retries
    :type max_retry_interval: int

    :param _errors: the exception list that needs to be check

    :param exception_checker: checks if an exception should trigger a retry
    :type exception_checker: callable
    """

    def __init__(self, retry_interval=0, max_retries=0, inc_retry_interval=0,
                 max_retry_interval=0, _errors=None,
                 exception_checker=lambda exc: False):
        super(wrap_func_retry, self).__init__()

        self._errors = _errors if _errors else []
        # default is that we re-raise anything unexpected
        self.exception_checker = exception_checker
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.inc_retry_interval = inc_retry_interval
        self.max_retry_interval = max_retry_interval

    def __call__(self, f):
        @six.wraps(f)
        def wrapper(*args, **kwargs):
            next_interval = self.retry_interval
            remaining = self.max_retries

            while True:
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    with excutils.save_and_reraise_exception() as ectxt:
                        if remaining > 0:
                            ectxt.reraise = not self._is_exception_expected(e)
                        else:
                            LOG.exception(_LE('Function exceeded '
                                              'retry limit.'))
                    LOG.debug("Performing retry for function %s",
                              reflection.get_callable_name(f))
                    # NOTE(vsergeyev): We are using patched time module, so
                    #                  this effectively yields the execution
                    #                  context to another green thread.
                    time.sleep(next_interval)
                    if self.inc_retry_interval:
                        next_interval = min(
                            next_interval * 2,
                            self.max_retry_interval
                        )
                    remaining -= 1
        return wrapper

    def _is_exception_expected(self, exc):
        for error in self._errors:
            if isinstance(exc, error):
                return True
        return self.exception_checker(exc)


class RateLimiter(object):
    def __init__(self, max_rate=3, time_unit=1, **kwargs):
        self.time_unit = time_unit
        self.deque = collections.deque(maxlen=max_rate)

    def __call__(self):
        if self.deque.maxlen == len(self.deque):
            cTime = time.time()
            if cTime - self.deque[0] > self.time_unit:
                self.deque.append(cTime)
                return False
            else:
                return True
        self.deque.append(time.time())
        return False
