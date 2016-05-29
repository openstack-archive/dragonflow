#!/bin/bash


function _neutron_ovs_get_dnf {
    if is_fedora; then
        if [ $OS_RELEASE -ge 22 ]; then
            echo "dnf"
        else
            echo "yum"
        fi
    else
        die "This function is only supported on fedora"
    fi
}

function _neutron_ovs_install_ovs_deps_fedora {
    DNF=`_neutron_ovs_get_dnf`
    sudo $DNF install -y rpm-build
    # So apparently we need to compile to learn the requirements...
    set `cat ../rhel/openvswitch-fedora.spec.in | sed 's/@VERSION@/0/' | rpmspec -q --buildrequires /dev/stdin`
    set "$@" `cat ../rhel/openvswitch-kmod-fedora.spec.in | sed 's/@VERSION@/0/' | rpmspec -q --buildrequires /dev/stdin`
    if [ $# > 0 ]; then
        sudo $DNF install -y $@
    fi
}

function _neutron_ovs_get_rpm_basename {
    PACKAGE=$1
    SPEC=${2:-../rhel/openvswitch-fedora.spec}
    BASENAME=`rpmspec -q $SPEC --provides | awk "/^$PACKAGE\s*=/ {print \\\$1\"-\"\\\$3}" |  head -1`
    echo `rpmspec -q $SPEC | grep "^$BASENAME"`
}

function _neutron_ovs_get_rpm_file {
    BASENAME=`_neutron_ovs_get_rpm_basename "$@"`
    find -name "$BASENAME.rpm" | head -1
}

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

function _neutron_ovs_install_ovs_fedora {
    _neutron_ovs_clone_ovs

    mkdir -p $DEST/ovs/build-dragonflow
    pushd $DEST/ovs/build-dragonflow

    pushd ..
    ./boot.sh
    popd

    ../configure
    make
    _neutron_ovs_install_ovs_deps_fedora
    make rpm-fedora RPMBUILD_OPT="--without check"
    make rpm-fedora-kmod
    OVS_RPM_BASENAME=`_neutron_ovs_get_rpm_file openvswitch`
    OVS_PY_RPM_BASENAME=""
    OVS_KMOD_RPM_BASENAME=`_neutron_ovs_get_rpm_file openvswitch-kmod ../rhel/openvswitch-kmod-fedora.spec`
    DNF=`_neutron_ovs_get_dnf`
    sudo $DNF install -y $OVS_RPM_BASENAME $OVS_PY_RPM_BASENAME $OVS_KMOD_RPM_BASENAME
    sudo pip install ../python

    popd
}

function _neutron_ovs_install_ovs_deps_ubuntu {
    sudo apt-get install -y build-essential fakeroot devscripts equivs dkms
    sudo mk-build-deps -i -t "/usr/bin/apt-get --no-install-recommends -y"
}

function _neutron_ovs_install_ovs_ubuntu {
    _neutron_ovs_clone_ovs

    pushd $DEST/ovs
    _neutron_ovs_install_ovs_deps_ubuntu
    DEB_BUILD_OPTIONS='nocheck' fakeroot debian/rules binary
    sudo dpkg -i ../openvswitch-datapath-dkms*.deb
    sudo dpkg -i ../openvswitch-common*.deb ../openvswitch-switch*.deb
    sudo pip install python
    popd
}

function _neutron_ovs_install_ovs {
    if [ "$OVS_INSTALL_FROM_GIT" == "True" ]; then
        echo "Installing OVS and dependent packages from git"
        # If OVS is already installed, remove it, because we're about to re-install
        # it from source.
        for package in openvswitch openvswitch-switch openvswitch-common; do
            if is_package_installed $package ; then
                uninstall_package $package
            fi
        done

        # try to unload openvswitch module from kernel
        if test -n "`lsmod | grep openvswitch`"; then
            sudo modprobe -r openvswitch
        fi

        if is_ubuntu; then
            _neutron_ovs_install_ovs_ubuntu
        elif is_fedora; then
            _neutron_ovs_install_ovs_fedora
        else
            echo "Unsupported system. Trying to install via package manager"
            install_package $(get_packages "openvswitch")
        fi
    else
        echo "Installing OVS and dependent packages via package manager"
        install_package $(get_packages "openvswitch")
    fi
}

function install_ovs {
    _neutron_ovs_install_ovs
}

function start_ovs {
    echo "Starting OVS"
    SERVICE_NAME=openvswitch  # Default value
    if is_fedora; then
        SERVICE_NAME=openvswitch
    elif is_ubuntu; then
        SERVICE_NAME=openvswitch-switch
    fi

    start_service $SERVICE_NAME

    local _pwd=$(pwd)
    cd $DATA_DIR/ovs

    if ! ovs_service_status $OVS_DB_SERVICE; then
       die "$OVS_DB_SERVICE is not running"
    fi

    if is_service_enabled df-controller ; then
        if ! ovs_service_status $OVS_VSWITCHD_SERVICE; then
            die "$OVS_VSWITCHD_SERVICE is not running"
        fi
        load_module_if_not_loaded openvswitch
        # TODO This needs to be a fatal error when doing multi-node testing, but
        # breaks testing in OpenStack CI where geneve isn't available.
        load_module_if_not_loaded geneve || true
        load_module_if_not_loaded vport_geneve || true

        _neutron_ovs_base_setup_bridge br-int
        sudo ovs-vsctl --no-wait set bridge br-int fail-mode=secure other-config:disable-in-band=true

        # setup external bridge if necessary
        check_dnat=$(echo $DF_APPS_LIST | grep "DNATApp")
        if [[ "$check_dnat" != "" ]]; then
            echo "Setup external bridge for DNAT"
            sudo ovs-vsctl add-br $PUBLIC_BRIDGE || true
        fi
    fi

    cd $_pwd
}

function cleanup_ovs {
    # Remove the patch ports
    for port in $(sudo ovs-vsctl show | grep Port | awk '{print $2}'  | cut -d '"' -f 2 | grep patch); do
        sudo ovs-vsctl del-port ${port}
    done

    # remove all OVS ports that look like Neutron created ports
    for port in $(sudo ovs-vsctl list port | grep -o -e tap[0-9a-f\-]* -e q[rg]-[0-9a-f\-]*); do
        sudo ovs-vsctl del-port ${port}
    done

    # Remove all the vxlan ports
    for port in $(sudo ovs-vsctl list port | grep name | grep vxlan | awk '{print $3}'  | cut -d '"' -f 2); do
        sudo ovs-vsctl del-port ${port}
    done

}

function uninstall_ovs {
        sudo pip uninstall -y ovs
        PACKAGES="openvswitch openvswitch-kmod openvswitch-switch openvswitch-common openvswitch-datapath-dkms"
        for package in $PACKAGES; do
            if is_package_installed $package ; then
                uninstall_package $package
            fi
        done
}

# stop_ovs_dp() - Stop OVS datapath
function stop_ovs_dp {
    sudo ovs-dpctl dump-dps | sudo xargs -n1 ovs-dpctl del-dp
    sudo rmmod vport_geneve
    sudo rmmod openvswitch
}

function stop_ovs
{
    stop_ovs_dp

    SERVICE_NAME=openvswitch  # Default value
    if is_fedora; then
        SERVICE_NAME=openvswitch
    elif is_ubuntu; then
        SERVICE_NAME=openvswitch-switch
    fi
    stop_service $SERVICE_NAME
}
