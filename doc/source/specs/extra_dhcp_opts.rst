..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=======================
Support extra-dhcp-opts
=======================


Problem Description
===================
For enable to users to configure custom dhcp-options neutron-api
supply the extra-dhcp-opts extension [1]_.

According to RFC 2131 [2]_  -  dhcp-options is list that composed from
tags-values pairs - when  tag is number in the rage of 0-255,
and the value is a variable-length byte-sequence.
(for example RFC 2132 [3]_ defines list dhcp options
for BOOTP vendor-extensions).

Neutron spec define the  extra-extra-dhcp-opts as a set of pairs
that each pair combined from opt_name and opt_value [1]_ , but the spec
didn't not define how opt_name should be translated to dhcp-opt number.

According to the examples in the spec, and according to neutron reference
implementation, the format of the option names is derived from the
configuration file of dnsmsq-dhcp server ( as it used as the server in the
reference implementation ). In addition that configuration enables to
configure fields in the dhcp-packet itself (the  "server-ip-address"
as it change the  siaddr -  that isn't part of the
options-scope in the dhcp-packet [2]_).

In dragonflow we are using custom dhcp-app for supporting our
distributed-dhcp solution [4]_ . This app currently returns a
pre-defined set of dhcp-optios , ans not using the lports' extra-dhcp-opt
attribute.

We want to propose a new implementation that supports the extra-dhcp-option -
By supporting the opt-name in format of dnsmasq-conf , alongside with other
configurations format (for example: dhcpd.conf format or by supplying the tags
directly as a number - "11" for dhcp-opt 11).


Proposed Change
===============

in the proposed change we want to:

* Define language that acceptable as dhcp-tag by the df-dhcp-app in
  controller (the numbers 0-255 and all the supported-fields as they
  defined in the RFC [2]_). that language will be used for storing
  the objects in the Nb-api.

* For defining that language, a field type of dhcp-opts-dictionary will
  be added to the NB-db. That field will be composed from a set of the
  supported-fields, and a dictionary (string->string) When each key in
  the dictionary must be validate against supported-fields set.

* In the L2 mech-driver - add code that translate the opt_name  from the
  api supported language to the language that supported by
  the dhcp-app  that described above (in case of unknown option -
  port creation should fail)

* In the DHCP app - add code that answers to the dhcp requests according to
  the configured dhcp-opts.


Execution workflow:
===================

* User generate an  neutron-lport-create api-request with :

.. code-block:: json

  {"extra_dhcp_opts":[{"opt_value": "testfile.1", "opt_name": "bootfile-name"}]}

* l2 plugin will translate it to:

.. code-block:: json

  {"extra_dhcp_opts":{"67": "testfile.1"}}

* The lport will be stored in the NB-db.
* The dhcp-app will use that value for answering request that ask for
  dhcp-option 67.






References
==========
.. [#] https://specs.openstack.org/openstack/neutron-specs/specs/api/extra_dhcp_options__extra-dhcp-opt\_.html
.. [#] https://tools.ietf.org/html/rfc2131
.. [#] https://tools.ietf.org/html/rfc2132
.. [#] https://github.com/openstack/dragonflow/blob/master/doc/source/distributed_dhcp.rst


