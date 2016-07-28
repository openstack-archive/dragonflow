#!/bin/bash

DPDK_VERSION=16.07
DPDK_DIR=$DEST/dpdk/dpdk-${DPDK_VERSION}
DPDK_TARGET=x86_64-native-linuxapp-gcc
DPDK_BUILD=$DPDK_DIR/$DPDK_TARGET

PCI_BUS_INFO=`sudo ethtool -i ${DPDK_NIC_NAME} | grep bus-info`
DPDK_PCI_TARGET=${PCI_BUS_INFO#*:}

# COPY from ovs_setup.sh
function _neutron_ovs_get_dnf {
    if is_fedora; then
        if [ $os_RELEASE -ge 22 ]; then
            echo "dnf"
        else
            echo "yum"
        fi
    else
        die "This function is only supported on fedora"
    fi
}

# COPY from ovs_setup.sh
function _neutron_ovs_clone_ovs {
    if [ -d $DEST/ovs ]; then
        pushd $DEST/ovs
        git checkout $OVS_BRANCH
        git pull
        popd
    else
        pushd $DEST
        git clone $OVS_REPO -b $OVS_BRANCH
        popd
    fi
}

function _neutron_ovs_install_dependencies {
    if is_fedora; then
        DNF=${1:-`_neutron_ovs_get_dnf`}
        sudo $DNF install -y kernel-devel
    elif is_ubuntu; then
        sudo apt-get install -y build-essential
    fi

    if [ ! -e /sys/class/misc/tun]; then
        sudo modprobe tun
    fi
    if [ ! -e /dev/net/tun]; then
        sudo mkdir -p /dev/net
        sudo mknod /dev/net/tun c 10 200
    fi
}

function _configure_ovs_dpdk {
    # By default, dragonflow uses OVS kernel datapath. If you want to use
    # user space datapath powered by DPDK, please use 'netdev'.
    OVS_DATAPATH_TYPE=netdev

    # Configure user space datapath
    iniset $NEUTRON_CONF df vif_type vhostuser
    iniset $NEUTRON_CONF df vhost_sock_dir ${OVS_DIR}

    # Configure huge-pages
    sudo sysctl -w vm.nr_hugepages=${DPDK_NUM_OF_HUGEPAGES}
    sudo mkdir -p /dev/hugepages
    sudo mount -t hugetlbfs none /dev/hugepages

    # Disable kernel TCP/IP stack
    sudo iptables -A INPUT -i ${DPDK_NIC_NAME} -j DROP
    sudo iptables -A FORWARD -i ${DPDK_NIC_NAME} -j DROP

    # Configure UIO
    sudo modprobe uio
    sudo insmod $DPDK_BUILD/kmod/${DPDK_BIND_DRIVER}.ko

    # Set up DPDK NIC
    sudo ip link set ${DPDK_NIC_NAME} down
    sudo dpdk_nic_bind --bind=${DPDK_BIND_DRIVER} ${DPDK_PCI_TARGET}

    # Configure Open vSwitch to connect dpdk-enabled physical NIC
    # to the OVS bridge. For example:
    sudo ovs-vsctl add-port ${INTEGRATION_BRIDGE} dpdk0 -- set interface \
        dpdk0 type=dpdk ofport_request=1
}

function _install_dpdk {
    mkdir -p $DEST/dpdk
    pushd $DEST/dpdk
    if [ ! -e $DEST/dpdk/dpdk-${DPDK_VERSION}.zip ]
    then
        wget http://dpdk.org/browse/dpdk/snapshot/dpdk-${DPDK_VERSION}.zip
    fi
    unzip dpdk-${DPDK_VERSION}.zip
    cd $DPDK_DIR
    sudo make install T=$DPDK_TARGET DESTDIR=install
    popd
}

function _uninstall_dpdk {
    sudo dpdk_nic_bind -u ${DPDK_PCI_TARGET}
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
    _neutron_ovs_install_dependencies
    _install_dpdk
    _neutron_ovs_clone_ovs

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
    rm $DATA_DIR/ovs/conf.db

    # Start OVSDB
    sudo ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
          --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
          --private-key=db:Open_vSwitch,SSL,private_key \
          --certificate=Open_vSwitch,SSL,certificate \
          --bootstrap-ca-cert=db:Open_vSwitch,SSL,ca_cert --pidfile --detach

    # Start vswitchd
    sudo ovs-vsctl --no-wait init
    export DB_SOCK=/var/run/openvswitch/db.sock
    sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
    sudo ovs-vswitchd unix:$DB_SOCK --pidfile --detach
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
