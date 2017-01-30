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

from neutron_lib import exceptions
from oslo_utils import excutils
import six

from dragonflow._i18n import _


class DragonflowException(Exception):
    """Base Dragonflow Exception.

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.
    """
    message = _("An unknown exception occurred.")

    def __init__(self, **kwargs):
        try:
            super(DragonflowException, self).__init__(self.message % kwargs)
            self.msg = self.message % kwargs
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                if not self.use_fatal_exceptions():
                    ctxt.reraise = False
                    # at least get the core message out if something happened
                    super(DragonflowException, self).__init__(self.message)

    if six.PY2:
        def __unicode__(self):
            return unicode(self.msg)

    def __str__(self):
        return self.msg

    def use_fatal_exceptions(self):
        return False


class DBKeyNotFound(DragonflowException):
    message = _('DB Key not found, key=%(key)s')


class CommandError(DragonflowException):
    message = _("Non-existent fields are specified: %(non_existent_fields)s")


class UnsupportedTransportException(DragonflowException):
    """
    An exception for cases when the given transport protocol (e.g. UDP, TCP) is
    not supported.
    """
    message = _("Transport protocol is not supported: %(transport)s")


class DBLockFailed(DragonflowException):
    message = _("The DB Lock cannot be acquired for object=%(oid)s in"
                "the session=%(sid)s.")


class DBStoreRecordNotFound(DragonflowException):
    message = _('%(record)s not found in db_store!')


class NoRemoteIPProxyException(DragonflowException):
    message = _('The metadata request has no remote IP')


class InvalidIPAddressException(DragonflowException):
    message = _('The IP address %(key)s is invalid')


class LogicalPortNotFoundByTunnelKey(DragonflowException):
    message = _('Could not find logical port with tunnel key %(key)')


class DFMultipleExceptions(exceptions.MultipleExceptions):

    def __str__(self):
        return ','.join(str(error) for error in self.inner_exceptions)


class UnknownResourceException(DragonflowException):
    message = _('Could not find lock id for resource type %(resource_type)')


class InvalidDBHostConfiguration(DragonflowException):
    message = _('The DB host string %(host)s is invalid.')


class OutOfCookieSpaceException(DragonflowException):
    message = _('Out of cookie space.')


class MaskOverlapException(DragonflowException):
    message = _('Cookie mask overlap for cookie %(app_name)s/%(name)s')


class CookieOverflowExcpetion(DragonflowException):
    message = _('Cookie overflow: '
                'Value: %(cookie)s Offset: %(offset)s Mask: %(mask)s')
