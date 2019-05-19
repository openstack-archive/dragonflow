# -*- mode: ruby -*-
# vi: set ft=ruby :

# Install vagrant-env plugin: vagrant plugin install vagrant-env

# Start the machines one by one, so we can have the controller up
# before the compute nodes start
ENV['VAGRANT_NO_PARALLEL'] = 'yes'

# libvirt boxes: https://app.vagrantup.com/boxes/search?provider=libvirt&q=ubuntu
# VirtualBox boxes: https://app.vagrantup.com/boxes/search?provider=virtualbox&q=ubuntu

require 'yaml'

vagrant_config = YAML.load_file("provisioning/dragonflow.conf.yml")

Vagrant.configure(2) do |config|
  config.vm.box = vagrant_config['box']

  if Vagrant.has_plugin?("vagrant-cachier")
    # Configure cached packages to be shared between instances of the same base box.
    # More info on http://fgrehm.viewdocs.io/vagrant-cachier/usage
    config.cache.scope = :box
  end

  config.vm.synced_folder '..', '/dragonflow'

  config.vm.provider 'parallels' do |vb, override|
     vb.customize ['set', :id, '--nested-virt', 'on']
     override.vm.box = ENV.fetch('VAGRANT_OVN_VM_BOX', 'box-cutter/ubuntu1604')
  end
  config.vm.provider 'libvirt' do |vb, override|
     vb.nested        = true
     override.vm.box = ENV.fetch('VAGRANT_OVN_VM_BOX', 'generic/ubuntu1804')
  end

  # Bring up the Devstack controller node on the hypervisor
  config.vm.define "devstack_controller" do |devstack_controller|
    devstack_controller.vm.host_name = vagrant_config['devstack_controller']['host_name']
    devstack_controller.vm.network "private_network", ip: vagrant_config['devstack_controller']['ip']
    devstack_controller.vm.provision "shell", path: "provisioning/setup-base.sh", privileged: false
    devstack_controller.vm.provision "shell", path: "provisioning/setup-controller.sh", privileged: false

    config.vm.provider "virtualbox" do |vb|
       vb.memory = vagrant_config['devstack_controller']['memory']
       vb.cpus = vagrant_config['devstack_controller']['cpus']
    end
    config.vm.provider 'parallels' do |vb|
       vb.memory = vagrant_config['devstack_controller']['memory']
       vb.cpus = vagrant_config['devstack_controller']['cpus']
    end
    config.vm.provider 'libvirt' do |vb|
       vb.memory = vagrant_config['devstack_controller']['memory']
       vb.cpus = vagrant_config['devstack_controller']['cpus']
    end
  end

  # Bring up the Devstack compute nodes on the hypervisor
  (1..2).each do |i|
    config.vm.define "devstack_compute#{i}" do |devstack_compute|
      devstack_compute.vm.host_name = vagrant_config["devstack_compute#{i}"]['host_name']
      devstack_compute.vm.network "private_network", ip: vagrant_config["devstack_compute#{i}"]['ip']
      devstack_compute.vm.provision "shell", path: "provisioning/setup-base.sh", privileged: false
      devstack_compute.vm.provision "shell", path: "provisioning/setup-compute.sh", privileged: false, :args => "#{vagrant_config['devstack_controller']['ip']}"

      config.vm.provider "virtualbox" do |vb|
         vb.memory = vagrant_config["devstack_compute#{i}"]['memory']
         vb.cpus = vagrant_config["devstack_compute#{i}"]['cpus']
      end
      config.vm.provider 'parallels' do |vb|
         vb.memory = vagrant_config["devstack_compute#{i}"]['memory']
         vb.cpus = vagrant_config["devstack_compute#{i}"]['cpus']
      end
      config.vm.provider 'libvirt' do |vb|
         vb.memory = vagrant_config["devstack_compute#{i}"]['memory']
         vb.cpus = vagrant_config["devstack_compute#{i}"]['cpus']
      end
    end
  end

  # Define the Devstack All-In-One node on Hypervisor
  config.vm.define "devstack_aio", autostart: false do |devstack_aio|
    devstack_aio.vm.host_name = vagrant_config['devstack_aio']['host_name']
    devstack_aio.vm.network "private_network", ip:vagrant_config['devstack_aio']['ip']
    devstack_aio.vm.provision "shell", path: "provisioning/setup-base.sh", privileged: false
    devstack_aio.vm.provision "shell", path: "provisioning/setup-aio.sh", privileged: false

    config.vm.provider "virtualbox" do |vb|
       vb.memory = vagrant_config['devstack_aio']['memory']
       vb.cpus = vagrant_config['devstack_aio']['cpus']
    end
    config.vm.provider 'parallels' do |vb|
       vb.memory = vagrant_config['devstack_aio']['memory']
       vb.cpus = vagrant_config['devstack_aio']['cpus']
    end
    config.vm.provider 'libvirt' do |vb|
       vb.memory = vagrant_config['devstack_aio']['memory']
       vb.cpus = vagrant_config['devstack_aio']['cpus']
    end
  end

end
