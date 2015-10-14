============
Installation
============

At the command line::

    $ pip install dragonflow

Or, if you have virtualenvwrapper installed::

    $ mkvirtualenv dragonflow
    $ pip install dragonflow

============================================
 Automated setup using Vagrant + Virtualbox
============================================

This will create a 2 nodes devstack (controller + compute), where Dragonflow is used as
the Open vSwitch backend.

Vagrant allows to configure the provider on which the virtual machines are
created. Virtualbox is the default provider used to launch the VM's on a
developer computer, but other providers can be used: VMWare, AWS, Openstack,
containers stuff, ...

Quick Start
-----------

1. Install Virtualbox (https://www.virtualbox.org/wiki/Downloads) and Vagrant
   (http://downloads.vagrantup.com).

2. Configure

::

    git clone https://git.openstack.org/openstack/dragonflow
    cd dragonflow
    vagrant plugin install vagrant-cachier
    vagrant plugin install vagrant-vbguest

3. Adjust the settings in `devstack/vagrant.conf.yml` if needed (5GB RAM is the
   minimum to get 1 VM running on the controller node)

4. Launch the VM's: `vagrant up`

... This may take a while, once it is finished:

* you can ssh into the virtual machines: `vagrant ssh devstack_controller` or
  `vagrant ssh devstack_compute`

* you can access the horizon dashboard at http://controller.devstack.dev

* the dragonflow folder is shared between the host and the two nodes (at
  /home/vagrant/dragonflow)
