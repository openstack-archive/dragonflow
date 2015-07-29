# dragonflow.sh - Devstack extras script to install Dragonflow

# The git repo to use
OVN_REPO=${OVN_REPO:-http://github.com/openvswitch/ovs.git}
OVN_REPO_NAME=$(basename ${OVN_REPO} | cut -f1 -d'.')

# The branch to use from $OVN_REPO
OVN_BRANCH=${OVN_BRANCH:-origin/master}

# How to connect to ovsdb-server hosting the OVN databases.
OVN_REMOTE_IP=${OVN_REMOTE_IP:-$HOST_IP}
OVN_REMOTE=${OVN_REMOTE:-tcp:$OVN_REMOTE_IP:6640}

# A UUID to uniquely identify this system.  If one is not specified, a random
# one will be generated.  A randomly generated UUID will be saved in a file
# 'ovn-uuid' so that the same one will be re-used if you re-run DevStack.
OVN_UUID=${OVN_UUID:-}

# Utility Functions
# -----------------

function is_ovn_service_enabled {
    ovn_service=$1
    is_service_enabled ovn && return 0
    is_service_enabled $ovn_service && return 0
    return 1
}


# Entry Points
# ------------

# cleanup_ovn() - Remove residual data files, anything left over from previous
# runs that a clean run would need to clean up
function cleanup_ovn {
    :
}

# configure_ovn() - Set config files, create data dirs, etc
function configure_ovn {
    echo "Configuring OVN"

    if [ -z "$OVN_UUID" ] ; then
        if [ -f ./ovn-uuid ] ; then
            OVN_UUID=$(cat ovn-uuid)
        else
            OVN_UUID=$(uuidgen)
            echo $OVN_UUID > ovn-uuid
        fi
    fi
}

function configure_ovn_plugin {
    echo "Configuring Neutron for OVN"

    if is_service_enabled q-svc ; then
        # NOTE(arosen) needed for tempest
        export NETWORK_API_EXTENSIONS='binding,quotas,agent,dhcp_agent_scheduler,external-net,router'
        Q_PLUGIN_CLASS="networking_ovn.plugin.OVNPlugin"

        NEUTRON_CONF=/etc/neutron/neutron.conf
        iniset $NEUTRON_CONF ovn ovsdb_connection "$OVN_REMOTE"
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""
    fi
}

# init_ovn() - Initialize databases, etc.
function init_ovn {
    # clean up from previous (possibly aborted) runs
    # create required data files

    # Assumption: this is a dedicated test system and there is nothing important
    # in the ovn, ovn-nb, or ovs databases.  We're going to trash them and
    # create new ones on each devstack run.

    base_dir=$DATA_DIR/ovs
    mkdir -p $base_dir

    for db in conf.db ovnsb.db ovnnb.db ; do
        if [ -f $base_dir/$db ] ; then
            rm -f $base_dir/$db
        fi
    done
    rm -f $base_dir/.*.db.~lock~

    echo "Creating OVS, OVN-Southbound and OVN-Northbound Databases"
    ovsdb-tool create $base_dir/conf.db $DEST/$OVN_REPO_NAME/vswitchd/vswitch.ovsschema
    if is_ovn_service_enabled ovn-northd ; then
        ovsdb-tool create $base_dir/ovnsb.db $DEST/$OVN_REPO_NAME/ovn/ovn-sb.ovsschema
        ovsdb-tool create $base_dir/ovnnb.db $DEST/$OVN_REPO_NAME/ovn/ovn-nb.ovsschema
    fi
}

function install_df {
    echo_summary "Installing DragonFlow"

    git_clone $DRAGONFLOW_REPO $DRAGONFLOW_DIR $DRAGONFLOW_BRANCH

    echo "Cloning and installing Ryu"
    git_clone $RYU_REPO $RYU_DIR $RYU_BRANCH
    pushd $RYU_DIR
    setup_package ./ -e
    popd
    echo "Finished installing Ryu"
}

# install_ovn() - Collect source and prepare
function install_ovn {
    local _pwd=$(pwd)
    echo "Installing OVN and dependent packages"

    # If OVS is already installed, remove it, because we're about to re-install
    # it from source.
    for package in openvswitch openvswitch-switch openvswitch-common; do
        if is_package_installed $package ; then
            uninstall_package $package
        fi
    done

    if ! is_neutron_enabled ; then
        # networking-ovn depends on neutron, so ensure it at least gets
        # installed.
        install_neutron
    fi

    git_clone $NETWORKING_OVN_REPO $DEST/networking-ovn master

    echo "Patching OVN from Dragonflow"
    cp $DEST/dragonflow/ovn-patch/commands.py $DEST/networking-ovn/networking_ovn/ovsdb/commands.py
    cp $DEST/dragonflow/ovn-patch/impl_idl_ovn.py $DEST/networking-ovn/networking_ovn/ovsdb/impl_idl_ovn.py
    cp $DEST/dragonflow/ovn-patch/ovn_api.py $DEST/networking-ovn/networking_ovn/ovsdb/ovn_api.py
    cp $DEST/dragonflow/ovn-patch/plugin.py $DEST/networking-ovn/networking_ovn/plugin.py
    cp $DEST/dragonflow/ovn-patch/constants.py $DEST/networking-ovn/networking_ovn/common/constants.py

    echo "Installing networking-ovn"
    setup_develop $DEST/networking-ovn

    cd $DEST
    if [ ! -d $OVN_REPO_NAME ] ; then
        git clone $OVN_REPO
        cd $OVN_REPO_NAME
        git checkout $OVN_BRANCH
    else
        cd $OVN_REPO_NAME
    fi

    cp $DEST/dragonflow/ovn-patch/ovn-nb.ovsschema $DEST/ovs/ovn/ovn-nb.ovsschema
    cp $DEST/dragonflow/ovn-patch/ovn-nb.xml $DEST/ovs/ovn/ovn-nb.xml

    # TODO: Can you create package list files like you can inside devstack?
    install_package autoconf automake libtool gcc patch make

    if [ ! -f configure ] ; then
        ./boot.sh
    fi
    if [ ! -f config.status ] || [ configure -nt config.status ] ; then
        ./configure
    fi
    make -j$[$(nproc) + 1]
    sudo make install
    sudo chown $(whoami) /usr/local/var/run/openvswitch
    sudo chown $(whoami) /usr/local/var/log/openvswitch

    cd $_pwd
}

function start_ovs {
    echo "Starting OVS"

    local _pwd=$(pwd)
    cd $DATA_DIR/ovs

    EXTRA_DBS=""
    OVSDB_REMOTE="--remote=ptcp:6640:$HOST_IP"
    if is_ovn_service_enabled ovn-northd ; then
        EXTRA_DBS="ovnsb.db ovnnb.db"
    fi

    ovsdb-server --remote=punix:/usr/local/var/run/openvswitch/db.sock \
                 --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
                 --pidfile --detach -vconsole:off --log-file $OVSDB_REMOTE \
                 conf.db ${EXTRA_DBS}

    echo -n "Waiting for ovsdb-server to start ... "
    while ! test -e /usr/local/var/run/openvswitch/db.sock ; do
        sleep 1
    done
    echo "done."
    ovs-vsctl --no-wait init
    ovs-vsctl --no-wait set open_vswitch . system-type="devstack"
    ovs-vsctl --no-wait set open_vswitch . external-ids:system-id="$OVN_UUID"
    if is_ovn_service_enabled df-controller ; then
        sudo modprobe openvswitch || die $LINENO "Failed to load openvswitch module"
        # TODO This needs to be a fatal error when doing multi-node testing, but
        # breaks testing in OpenStack CI where geneve isn't available.
        #sudo modprobe geneve || die $LINENO "Failed to load geneve module"
        sudo modprobe geneve || true
        #sudo modprobe vport_geneve || die $LINENO "Failed to load vport_geneve module"
        sudo modprobe vport_geneve || true

        ovs-vsctl --no-wait set open_vswitch . external-ids:ovn-remote="$OVN_REMOTE"
        ovs-vsctl --no-wait set open_vswitch . external-ids:ovn-bridge="br-int"
        ovs-vsctl --no-wait set open_vswitch . external-ids:ovn-encap-type="geneve"
        ovs-vsctl --no-wait set open_vswitch . external-ids:ovn-encap-ip="$HOST_IP"

        _neutron_ovs_base_setup_bridge br-int
        ovs-vsctl --no-wait set bridge br-int fail-mode=secure other-config:disable-in-band=true

        sudo ovs-vswitchd --pidfile --detach -vconsole:off --log-file
    fi

    cd $_pwd
}

# start_ovn() - Start running processes, including screen
function start_ovn {
    echo "Starting OVN"

    if is_ovn_service_enabled df-controller ; then
        ovs-vsctl --no-wait set-controller br-int tcp:$HOST_IP:6633
        run_process df-controller "python $DF_LOCAL_CONTROLLER $OVN_UUID $HOST_IP $OVN_REMOTE_IP"
    fi

    if is_ovn_service_enabled ovn-northd ; then
        run_process ovn-northd "ovn-northd --log-file"
    fi
}

# stop_ovn() - Stop running processes (non-screen)
function stop_ovn {
    if is_ovn_service_enabled df-controller ; then
        stop_process df-controller
        sudo killall ovs-vswitchd
    fi
    if is_ovn_service_enabled ovn-northd ; then
        stop_process ovn-northd
    fi
    sudo killall ovsdb-server
}

function disable_libvirt_apparmor {
    if ! sudo aa-status --enabled ; then
        return 0
    fi
    # NOTE(arosen): This is used as a work around to allow newer versions
    # of libvirt to work with ovs configured ports. See LP#1466631.
    # requires the apparmor-utils
    install_package apparmor-utils
    # disables apparmor for libvirtd
    sudo aa-complain /etc/apparmor.d/usr.sbin.libvirtd
}

# main loop
if [[ "$Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        if [[ "$OFFLINE" != "True" ]]; then
            install_df
            install_ovn
        fi
        echo export PYTHONPATH=\$PYTHONPATH:$DRAGONFLOW_DIR:$RYU_DIR >> $RC_DIR/.localrc.auto
        configure_ovn
        init_ovn
        # We have to start at install time, because Neutron's post-config
        # phase runs ovs-vsctl.
        start_ovs
        disable_libvirt_apparmor
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        configure_ovn_plugin

        if is_service_enabled nova; then
            create_nova_conf_neutron
        fi

        start_ovn
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_ovn
        cleanup_ovn
    fi
fi

if [[ "$Q_ENABLE_DRAGONFLOW" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "DragonFlow pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing DragonFlow"

        git_clone $DRAGONFLOW_REPO $DRAGONFLOW_DIR $DRAGONFLOW_BRANCH

        if is_service_enabled q-df-l3; then
           echo "Cloning and installing Ryu"
           git_clone $RYU_REPO $RYU_DIR $RYU_BRANCH
           #Don't use setup_develop, which is for openstack global requirement
           #compatible projects, and Ryu is not.
           pushd $RYU_DIR
           setup_package ./ -e
           popd
           echo "Finished installing Ryu"
        fi

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configure DragonFlow"

        if is_service_enabled q-df-l3; then
           _configure_neutron_l3_agent
        fi

        iniset $NEUTRON_CONF DEFAULT L3controller_ip_list $Q_DF_CONTROLLER_IP
        iniset /$Q_PLUGIN_CONF_FILE agent enable_l3_controller "True"
        iniset /$Q_PLUGIN_CONF_FILE agent L3controller_ip_list $Q_DF_CONTROLLER_IP

        echo export PYTHONPATH=\$PYTHONPATH:$DRAGONFLOW_DIR:$RYU_DIR >> $RC_DIR/.localrc.auto

        OVS_VERSION=`ovs-vsctl --version | head -n 1 | grep -E -o "[0-9]+\.[0-9]+\.[0-9]"`
        if [ `vercmp_numbers "$OVS_VERSION" "2.3.1"` -lt "0" ] && is_service_enabled q-agt ; then
            die $LINENO "You are running OVS version $OVS_VERSION. OVS 2.3.1+ is required for Dragonflow."
        fi

        echo summary "Dragonflow OVS version validated, version is $OVS_VERSION"

        echo summary "Setting L2 Agent to use Dragonflow Agent"
        AGENT_BINARY="$DF_L2_AGENT"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing DragonFlow"

        if is_service_enabled q-df-l3; then
            run_process q-df-l3 "python $DF_L3_AGENT --config-file $NEUTRON_CONF --config-file=$Q_L3_CONF_FILE"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled q-df-l3; then
           stop_process q-df-l3
        fi
    fi
fi
