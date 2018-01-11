..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 https://creativecommons.org/licenses/by/3.0/legalcode

===================
Import from Neutron
===================

launchpad RFE:

https://bugs.launchpad.net/dragonflow/+bug/1742621

Import from Neutron will allow us to both integrate into existing running
environment, taking all currently active configuration from the Neutron DB,
adding DragonFlow-enabled nodes. It will also allow users to migrate from a
setup running with Neutron reference implementation to DragonFlow enabled one.


Problem Description
===================

Currently the only valid installation of DragonFlow is clean install (upgrade
from previous DragonFlow is soon to come).
We would like to support the following use case:

Adding DragonFlow nodes to an existing environment running other openstack
networking implementations (e.g. reference implementation), this will allow a
deployer to evaluate the solution with little/no effect on the existing
environment. As DragonFlow will have the entire network information, it will
allow phasing out the previous implementation and moving to a pure DragonFlow
environment.


Proposed Change
===============

Final objective:

This solution will rely on the application decoupling spec [1].
Each application will define the objects that are of interest to it. For each
of these objects, a conversion class should be supplied.
If the conversion class resides in an external project, a reference to that
project must be supplied as well.

Note that it is up to the application to make sure that if an object is
dependent on another object, a converter for the latter should exist.

.. code:: python

  class SomeApp(AppBase):
      schematic = Contract(
          # List of application states
          states=(),

          # Outwards facing variables
          public_mapping=VariableMapping(),

          # Internal variables
          private_mapping=VariableMapping(),

          entrypoints=(),
      )
      neutron_convert = Converter(
          # Interesting neutron tables
          # Converting classes
      )

TODO: How do we specify this reference? can we add it to the requirements?
      We should make sure the project is there.
      Also, what happens if two apps need the same objects, but define
      different converters?

When the application starts, it checks if the northbound DB contains the
relevant table, if it does not, it will start converting the objects from the
Neutron DB to the DragonFlow northbound DB (making sure to convert the
underlying objects before it - to prevent dependency violation).


Intermediate solution:
We will have a CLI command that will iterate over the defined applications and
run the conversion code for each.
Note that order MUST be defined in some way to allow the applications using the
more basic objects convert them first.
- This command may be run when DragonFlow is installed.


References
==========

[1] https://github.com/openstack/dragonflow/blob/master/doc/source/specs/application_decoupling.rst
