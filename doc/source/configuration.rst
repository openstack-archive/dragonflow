==============
Configurations
==============

Since Newton, configuration files are not maintained in the git repository but
should be generated as follows::

``tox -e genconfig``

If a 'tox' environment is unavailable, then you can run the following script
instead to generate the configuration files::

./tools/generate_config_file_samples.sh
