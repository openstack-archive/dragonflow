#!/bin/bash

DPDK_VERSION=16.07.2
DPDK_DIR=$DEST/dpdk/dpdk-stable-${DPDK_VERSION}
DPDK_TARGET=x86_64-native-linuxapp-gcc
DPDK_BUILD=$DPDK_DIR/$DPDK_TARGET

PCI_BUS_INFO=`sudo ethtool -i ${DPDK_NIC_NAME} | grep bus-info`
DPDK_PCI_TARGET=${PCI_BUS_INFO#*:}

OVS_DIR=/usr/local/var/run/openvswitch
OVSDB_SOCK=/usr/local/var/run/openvswitch/db.sock

# includes ovs_setup.sh
source $DEST/dragonflow/devstack/ovs_setup.sh

function _neutron_ovs_configure_dependencies {
    # Configure TUN
    if [ ! -e /sys/class/misc/tun]; then
        sudo modprobe tun
    fi
    if [ ! -e /dev/net/tun]; then
        sudo mkdir -p /dev/net
        sudo mknod /dev/net/tun c 10 200
    fi

    # Configure huge-pages
    sudo sysctl -w vm.nr_hugepages=${DPDK_NUM_OF_HUGEPAGES}
    sudo mkdir -p /dev/hugepages
    sudo mount -t hugetlbfs none /dev/hugepages

    # Configure UIO
    sudo modprobe uio || true
    sudo insmod $DPDK_BUILD/kmod/${DPDK_BIND_DRIVER}.ko || true
}

function _configure_ovs_dpdk {
    # Configure user space datapath
    iniset $DRAGONFLOW_CONF df vif_type vhostuser
    iniset $DRAGONFLOW_CONF df vhost_sock_dir ${OVS_DIR}

    # Disable kernel TCP/IP stack
    sudo iptables -A INPUT -i ${DPDK_NIC_NAME} -j DROP
    sudo iptables -A FORWARD -i ${DPDK_NIC_NAME} -j DROP

    # Set up DPDK NIC
    sudo ip link set ${DPDK_NIC_NAME} down
    sudo $DPDK_DIR/tools/dpdk-devbind.py --bind=${DPDK_BIND_DRIVER} ${DPDK_PCI_TARGET}
}

function _install_dpdk {
    if is_fedora; then
        install_package kernel-devel
    elif is_ubuntu; then
        install_package build-essential
    fi

    if [ ! -d $DEST/dpdk ]; then
        mkdir -p $DEST/dpdk
        pushd $DEST/dpdk
        if [ ! -e $DEST/dpdk/dpdk-${DPDK_VERSION}.tar.xz ]
        then
            wget http://fast.dpdk.org/rel/dpdk-${DPDK_VERSION}.tar.xz
        fi
        tar xvJf dpdk-${DPDK_VERSION}.tar.xz
        cd $DPDK_DIR
        sudo make install T=$DPDK_TARGET DESTDIR=install
        popd
    fi
}

function _uninstall_dpdk {
    sudo $DPDK_DIR/tools/dpdk-devbind.py -u ${DPDK_PCI_TARGET}
    sudo rmmod $DPDK_BUILD/kmod/${DPDK_BIND_DRIVER}.ko
    sudo modprobe -r uio
    sudo ip link set ${DPDK_NIC_NAME} up

    # Enable kernel TCP/IP stack
    sudo iptables -D INPUT -i ${DPDK_NIC_NAME} -j DROP
    sudo iptables -D FORWARD -i ${DPDK_NIC_NAME} -j DROP

    pushd $DPDK_DIR
    sudo make uninstall
    popd
    sudo rm -rf $DPDK_DIR
}

function install_ovs {
    _install_dpdk
    _neutron_ovs_configure_dependencies
    _neutron_ovs_clone_ovs

    # If OVS is already installed, remove it, because we're about to re-install
    # it from source.
    for package in openvswitch openvswitch-switch openvswitch-common; do
        if is_package_installed $package ; then
            uninstall_package $package
        fi
    done

    install_package autoconf automake libtool gcc patch make

    pushd $DEST/ovs
    ./boot.sh
    ./configure --with-dpdk=$DPDK_BUILD
    make
    sudo make install
    sudo pip install ./python
    popd
}

function uninstall_ovs {
    sudo pip uninstall -y ovs
    pushd $DEST/ovs
    sudo make uninstall
    popd

    _uninstall_dpdk
}

function start_ovs {
    # First time, only DB creation/clearing
    sudo mkdir -p /var/run/openvswitch

    # Start OVSDB
    sudo ovsdb-server --remote=punix:$OVSDB_SOCK \
          --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
          --pidfile --detach

    # Start vswitchd
    sudo ovs-vsctl --db=unix:$OVSDB_SOCK --no-wait init
    sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
    sudo ovs-vswitchd unix:$OVSDB_SOCK --pidfile --detach
}

function configure_ovs {
    _configure_ovs_dpdk

    if is_service_enabled df-controller ; then
        # setup external bridge if necessary
        check_dnat=$(echo $DF_APPS_LIST | grep "DNATApp")
        if [[ "$check_dnat" != "" ]]; then
            echo "Setup external bridge for DNAT"
            sudo ovs-vsctl add-br $PUBLIC_BRIDGE || true
        fi

        _neutron_ovs_base_setup_bridge $INTEGRATION_BRIDGE
        sudo ovs-vsctl --no-wait set bridge $INTEGRATION_BRIDGE fail-mode=secure other-config:disable-in-band=true

        # Configure Open vSwitch to connect dpdk-enabled physical NIC
        # to the OVS bridge. For example:
        sudo ovs-vsctl add-port ${INTEGRATION_BRIDGE} dpdk0 -- set interface \
            dpdk0 type=dpdk ofport_request=1
    fi
}

function cleanup_ovs {
    # Remove the patch ports
    for port in $(sudo ovs-vsctl show | grep Port | awk '{print $2}' | cut -d '"' -f 2 | grep patch); do
        sudo ovs-vsctl del-port ${port}
    done

    # remove all OVS ports that look like Neutron created ports
    for port in $(sudo ovs-vsctl list port | grep -o -e tap[0-9a-f\-]* -e q[rg]-[0-9a-f\-]*); do
        sudo ovs-vsctl del-port ${port}
    done

    # Remove all the vxlan ports
    for port in $(sudo ovs-vsctl list port | grep name | grep vxlan | awk '{print $3}' | cut -d '"' -f 2); do
        sudo ovs-vsctl del-port ${port}
    done
}

function stop_ovs {
    sudo ovs-dpctl dump-dps | sudo xargs -n1 ovs-dpctl del-dp
    sudo killall ovsdb-server
    sudo killall ovs-vswitchd
}

function init_ovs {
    # clean up from previous (possibly aborted) runs
    # create required data files

    # Assumption: this is a dedicated test system and there is nothing important
    #  ovs databases.  We're going to trash them and
    # create new ones on each devstack run.

    base_dir=/usr/local/etc/openvswitch
    sudo mkdir -p $base_dir

    for db in conf.db ; do
        if [ -f $base_dir/$db ] ; then
            sudo rm -f $base_dir/$db
        fi
    done
    sudo rm -f $base_dir/.*.db.~lock~

    echo "Creating OVS Database"
    sudo ovsdb-tool create $base_dir/conf.db \
        /usr/local/share/openvswitch/vswitch.ovsschema
}
