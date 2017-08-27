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

Neutron spec define the  extra-dhcp-opts as a set of pairs
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

In the proposed change we want to:

* Define data-base model that will represent dhcp-parameters,
  This model will be used for saving the objects in the NB-API.

* The model will composed be key and value, when key is a string that's
  represent the parameter name,  and the value is an any field-type that
  suite for representing the data.

* Currently we planning to support the following dhcp-parameters:

  * opt - represent the dhcp-options, value represented by dictionary -
    when the key is value between 0-255 (represents the option-number),
    and the value is string (represents the opt-value).

  * siaddr - represents the siaddr field the dhcp-header. The value
    is represented by ip-address field.


* In the L2 mech-driver - add code that translate the opt_name from the
  api supported language to the dhcp-parameters object that
  described above (in case of unknown opt_name - port creation should fail).

* In the DHCP app - add code that answers to the dhcp requests according to
  the configured dhcp-params.


Execution workflow:
===================

* User generates an  neutron-lport-create api-request with :

.. code-block:: json

  {"extra_dhcp_opts":[{"opt_value": "testfile.1", "opt_name": "bootfile-name"},
                      {"opt_value": "192.168.0.100", "opt_name": "server-ip-address"}]
                      }

* l2 plugin will translate it to:

.. code-block:: json

  {
    "dhcp_params":{
      "opts" : {"67": "testfile.1"},
      "siaddr" : "192.168.0.100"
    }
  }

* The lport will be stored in the NB-db with dhcp opt attributes.
* The dhcp-app will use that value for answering request that ask for
  dhcp-option 67.






References
==========
.. [1] https://specs.openstack.org/openstack/neutron-specs/specs/api/extra_dhcp_options__extra-dhcp-opt\_.html
.. [2] https://tools.ietf.org/html/rfc2131
.. [3] https://tools.ietf.org/html/rfc2132
.. [4] https://github.com/openstack/dragonflow/blob/master/doc/source/distributed_dhcp.rst


