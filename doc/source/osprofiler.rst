..
  Licensed under the Apache License, Version 2.0 (the "License"); you may
  not use this file except in compliance with the License. You may obtain
  a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
  License for the specific language governing permissions and limitations
  under the License.

==========
OSProfiler
==========

OSProfiler provides a tiny but powerful library that is used by
most (soon to be all) OpenStack projects and their python clients. It
provides functionality to be able to generate one trace per request, that goes
through all involved services. This trace can then be extracted and used
to build a tree of calls which can be quite handy for a variety of
reasons (for example in isolating cross-project performance issues).

More about OSProfiler:
https://docs.openstack.org/osprofiler/latest/

Senlin supports using OSProfiler to trace the performance of each
key internal processing, including RESTful API, RPC, cluster actions,
node actions, DB operations etc.

Enabling OSProfiler
~~~~~~~~~~~~~~~~~~~

To configure DevStack to enable OSProfiler, edit the
``${DEVSTACK_DIR}/local.conf`` file and add::

    enable_plugin panko https://git.openstack.org/openstack/panko
    enable_plugin ceilometer https://git.openstack.org/openstack/ceilometer
    enable_plugin osprofiler https://git.openstack.org/openstack/osprofiler

to the ``[[local|localrc]]`` section.

.. note:: The order of the plugins enabling matters.

Using OSProfiler
~~~~~~~~~~~~~~~~

After successfully deploy your development environment, following profiler
configs will be auto added to ``dragonflow.conf``::

    [profiler]
    enabled = True
    trace_sqlalchemy = True
    hmac_keys = SECRET_KEY

``hmac_keys`` is the secret key(s) to use for encrypting context data for
performance profiling, default value is 'SECRET_KEY', you can modify it to
any random string(s).

Run any command with ``--os-profile SECRET_KEY``::

  $ openstack --os-profile SECRET_KEY floating ip create public
  # it will print a <Trace ID>

Get pretty HTML with traces::

  $ osprofiler trace show --html <Trace ID>
