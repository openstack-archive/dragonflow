..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================================
Configuration Refactoring and Generation
========================================

https://blueprints.launchpad.net/dragonflow/+spec/oslo-config-generator

This spec refactors the configurations and introduces oslo config generator
to auto-generate all the options for dragonflow.

Problem Description
===================

Currently dragonflow has many options for different modules. They are all
distributed and imported case by case. As more and more modules are going
to be introduced, we need to make them managed and centralized.

A good example is neutron[1].

Proposed Change
===============

1. Use a dedicated plugin conf file, instead of neutron.conf.

2. Use oslo config generator[2] to manages all the options.

Firstly, we use ``tox -e genconfig`` to generate all the conf files.
If tox is not prepared, we introduce ./tools/generate_config_file_samples.sh
instead.

Secondly, we use etc/oslo-config-generator/dragonflow.ini to manage oslo options.
For example::
[DEFAULT]
output_file = etc/dragonflow.ini.sample
wrap_width = 79
namespace = dragonflow
namespace = oslo.log

Finally, we implements dragonflow/opts.py to include all the references of options
from different modules of dragonflow.

References
==========
1. https://github.com/openstack/neutron/commit/71190773e14260fab96e78e65a290356cdc08581
2. http://docs.openstack.org/developer/oslo.config/generator.html
