#!/bin/bash

OVS_INSTALL_FROM_GIT=${OVS_INSTALL_FROM_GIT:-"True"}

function _neutron_ovs_install_ovs_deps_fedora {
    sudo dnf install -y rpm-build
    # So apparently we need to compile to learn the requirements...
    set `cat ../rhel/openvswitch-fedora.spec.in | sed 's/@VERSION@/0/' | rpmspec -q --buildrequires /dev/stdin`
    set "$@" `cat ../rhel/openvswitch-kmod-fedora.spec.in | sed 's/@VERSION@/0/' | rpmspec -q --buildrequires /dev/stdin`
    if [ $# > 0 ]; then
        sudo dnf install -y $@
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
        git checkout master
        git pull
        popd
    else
        pushd $DEST
        git clone $OVS_REPO
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
    OVS_PY_RPM_BASENAME=`_neutron_ovs_get_rpm_file python-openvswitch`
    OVS_KMOD_RPM_BASENAME=`_neutron_ovs_get_rpm_file openvswitch-kmod ../rhel/openvswitch-kmod-fedora.spec`
    sudo dnf install -y $OVS_RPM_BASENAME $OVS_PY_RPM_BASENAME $OVS_KMOD_RPM_BASENAME

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
    sudo dpkg -i ../openvswitch-common*.deb ../openvswitch-switch*.deb ../python-openvswitch*.deb
    popd
}

function _neutron_ovs_install_ovs {
    if [ "$OVS_INSTALL_FROM_GIT" == "True" ]; then
        echo "Installing OVS and dependent packages from git"
        # If OVS is already installed, remove it, because we're about to re-install
        # it from source.
        for package in openvswitch openvswitch-switch openvswitch-common; do
            # TODO(oanson)
            #mark_ovs_was_installed
            if is_package_installed $package ; then
                uninstall_package $package
            fi
        done

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
