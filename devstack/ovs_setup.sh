#!/bin/bash

function _neutron_ovs_install_ovs_deps_fedora {
    install_package -y rpm-build rpmrebuild
    # So apparently we need to compile to learn the requirements...
    set `rpmspec -q --buildrequires rhel/openvswitch-fedora.spec`
    set "$@" `rpmspec -q --buildrequires rhel/openvswitch-kmod-fedora.spec`
    if [ $# > 0 ]; then
        install_package -y $@
    fi
}

function _neutron_ovs_get_rpm_basename {
    PACKAGE=$1
    SPEC=${2:-rhel/openvswitch-fedora.spec}
    BASENAME=`rpmspec -q $SPEC --provides | awk "/^$PACKAGE\s*=/ {print \\\$1\"-\"\\\$3}" | head -1`
    echo `rpmspec -q $SPEC | grep "^$BASENAME"`
}

function _neutron_ovs_get_rpm_file {
    BASENAME=`_neutron_ovs_get_rpm_basename "$@"`
    find $HOME/rpmbuild/RPMS/ -name "$BASENAME.rpm" | head -1
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

    make dist
    VERSION=`awk '/^Version:/ { print $2 }' ../rhel/openvswitch-fedora.spec | head -1`

    mkdir -p $HOME/rpmbuild/SOURCES
    cp openvswitch-${VERSION}.tar.gz $HOME/rpmbuild/SOURCES/
    tar -xzf openvswitch-${VERSION}.tar.gz -C $HOME/rpmbuild/SOURCES
    pushd $HOME/rpmbuild/SOURCES/openvswitch-${VERSION}
    _neutron_ovs_install_ovs_deps_fedora
    rpmbuild -bb --without check rhel/openvswitch-fedora.spec
    rpmbuild -bb -D "kversion `uname -r`" rhel/openvswitch-kmod-fedora.spec
    OVS_RPM_BASENAME=$(_neutron_ovs_get_rpm_file openvswitch)
    rpmrebuild --change-spec-requires="awk '\$1 == \"Requires:\" && \$2 == \"/bin/python\" {\$2 = \"/usr/bin/python\"} {print \$0}'" -p $OVS_RPM_BASENAME
    OVS_PY_RPM_BASENAME=""
    OVS_KMOD_RPM_BASENAME=$(_neutron_ovs_get_rpm_file openvswitch-kmod rhel/openvswitch-kmod-fedora.spec)
    install_package -y $OVS_RPM_BASENAME $OVS_PY_RPM_BASENAME $OVS_KMOD_RPM_BASENAME
    sudo pip install ./python
    popd

    popd
}

function _neutron_ovs_install_ovs_deps_ubuntu {
    install_package -y build-essential fakeroot devscripts equivs dkms
    sudo mk-build-deps -i -t "/usr/bin/apt-get --no-install-recommends -y"
}

function _neutron_ovs_install_ovs_ubuntu {
    _neutron_ovs_clone_ovs

    pushd $DEST/ovs
    _neutron_ovs_install_ovs_deps_ubuntu
    DEB_BUILD_OPTIONS='nocheck' fakeroot debian/rules binary
    sudo dpkg -i ../openvswitch-datapath-dkms*.deb
    sudo dpkg -i ../openvswitch-common*.deb ../openvswitch-switch*.deb
    sudo pip install ./python
    popd
}

function _neutron_ovs_install_ovs {
    local _is_ovs_installed=false

    if [ "$OVS_INSTALL_FROM_GIT" == "True" ]; then
        echo "Installing OVS and dependent packages from git"
        # If OVS is already installed, remove it, because we're about to re-install
        # it from source.
        for package in openvswitch openvswitch-switch openvswitch-common; do
            if is_package_installed $package ; then
                _is_ovs_installed=true
                break
            fi
        done
        if [ "$_is_ovs_installed" = true ]; then
            cleanup_ovs
            stop_ovs
            uninstall_ovs
        fi

        install_package -y autoconf automake libtool gcc patch make

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

    # reload module
    load_module_if_not_loaded openvswitch
}

function start_ovs {
    echo "Starting OVS"
    SERVICE_NAME=openvswitch  # Default value
    if is_fedora; then
        SERVICE_NAME=openvswitch
    elif is_ubuntu; then
        SERVICE_NAME=openvswitch-switch
    fi

    restart_service $SERVICE_NAME
    sleep 5

    local _pwd=$(pwd)
    cd $DATA_DIR/ovs

    if ! ovs_service_status $OVS_DB_SERVICE; then
       die "$OVS_DB_SERVICE is not running"
    fi

    if is_service_enabled df-controller ; then
        if ! ovs_service_status $OVS_VSWITCHD_SERVICE; then
            die "$OVS_VSWITCHD_SERVICE is not running"
        fi
    fi

    cd $_pwd
}

function configure_ovs {
    if is_service_enabled df-controller ; then
        # setup external bridge if necessary
        check_dnat=$(echo $DF_APPS_LIST | grep "DNATApp")
        if [[ "$check_dnat" != "" ]]; then
            echo "Setup external bridge for DNAT"
            sudo ovs-vsctl add-br $PUBLIC_BRIDGE || true
        fi

        _neutron_ovs_base_setup_bridge $INTEGRATION_BRIDGE
        sudo ovs-vsctl --no-wait set bridge $INTEGRATION_BRIDGE fail-mode=secure other-config:disable-in-band=true
        if [ -n "$OVS_INTEGRATION_BRIDGE_PROTOCOLS" ]; then
            sudo ovs-vsctl set bridge $INTEGRATION_BRIDGE protocols=$OVS_INTEGRATION_BRIDGE_PROTOCOLS
        fi
    fi

    if [ -n "$OVS_MANAGER" ]; then
        sudo ovs-vsctl set-manager $OVS_MANAGER
    fi

    cd $_pwd
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

function uninstall_ovs {
    sudo pip uninstall -y ovs
    PACKAGES="openvswitch openvswitch-kmod openvswitch-switch openvswitch-common openvswitch-datapath-dkms"
    for package in $PACKAGES; do
        if is_package_installed $package ; then
            uninstall_package $package
        fi
    done

    # If the ovs dir is not found, just return.
    pushd $DEST/ovs || return 0
    make distclean || true
    popd
}

# stop_ovs_dp() - Stop OVS datapath
function stop_ovs_dp {
    dp=$(sudo ovs-dpctl dump-dps)
    if [ $dp ]; then
         sudo ovs-dpctl del-dp $dp
    fi

    # Here we just remove vport_<tunnel_type>, because this is a minimal
    # requirement to remove openvswitch. To do a deep clean, geneve, vxlan
    # ip_gre, gre also need to be removed.
    for module in vport_geneve vport_vxlan vport_gre openvswitch; do
        unload_module_if_loaded $module
    done
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

function init_ovs {
    # clean up from previous (possibly aborted) runs
    # create required data files

    # Assumption: this is a dedicated test system and there is nothing important
    #  ovs databases.  We're going to trash them and
    # create new ones on each devstack run.

    base_dir=$DATA_DIR/ovs
    mkdir -p $base_dir

    for db in conf.db ; do
        if [ -f $base_dir/$db ] ; then
            rm -f $base_dir/$db
        fi
    done
    rm -f $base_dir/.*.db.~lock~

    echo "Creating OVS Database"
    ovsdb-tool create $base_dir/conf.db $OVS_VSWITCH_OCSSCHEMA_FILE
}
