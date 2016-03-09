# dragonflow.sh - Devstack extras script to install Dragonflow

# The git repo to use
OVS_REPO=${OVS_REPO:-http://github.com/openvswitch/ovs.git}
OVS_REPO_NAME=$(basename ${OVS_REPO} | cut -f1 -d'.')

# The branch to use from $OVS_REPO
# TODO(gsagie) Currently take branch-2.5 branch as master is not stable
OVS_BRANCH=${OVS_BRANCH:-origin/branch-2.5}

DEFAULT_NB_DRIVER_CLASS="dragonflow.db.drivers.etcd_db_driver.EtcdDbDriver"
DEFAULT_TUNNEL_TYPE="geneve"
DEFAULT_APPS_LIST="l2_app.L2App,l3_proactive_app.L3ProactiveApp,dhcp_app.DHCPApp"

# How to connect to the database storing the virtual topology.
REMOTE_DB_IP=${REMOTE_DB_IP:-$HOST_IP}
REMOTE_DB_PORT=${REMOTE_DB_PORT:-4001}
REMOTE_DB_HOSTS=${REMOTE_DB_HOSTS:-"$REMOTE_DB_IP:$REMOTE_DB_PORT"}
NB_DRIVER_CLASS=${NB_DRIVER_CLASS:-$DEFAULT_NB_DRIVER_CLASS}
TUNNEL_TYPE=${TUNNEL_TYPE:-$DEFAULT_TUNNEL_TYPE}
DF_APPS_LIST=${DF_APPS_LIST:-$DEFAULT_APPS_LIST}

#pubsub
PUBLISHERS_HOSTS=${PUBLISHERS_HOSTS:-"$SERVICE_HOST"}

#ovs related pid files
OVS_DB_SERVICE="ovsdb-server"
OVS_VSWITCHD_SERVICE="ovs-vswitchd"
OVS_DIR="/usr/local/var/run/openvswitch"
OVS_DB_PID=$OVS_DIR"/"$OVS_DB_SERVICE".pid"
OVS_VSWITCHD_PID=$OVS_DIR"/"$OVS_VSWITCHD_SERVICE".pid"

# Pluggable DB drivers
#----------------------
if is_service_enabled df-etcd ; then
    source $DEST/dragonflow/devstack/etcd_driver
    NB_DRIVER_CLASS="dragonflow.db.drivers.etcd_db_driver.EtcdDbDriver"
fi
if is_service_enabled df-ramcloud ; then
    source $DEST/dragonflow/devstack/ramcloud_driver
    NB_DRIVER_CLASS="dragonflow.db.drivers.ramcloud_db_driver.RamCloudDbDriver"
fi
if is_service_enabled df-zookeeper ; then
    source $DEST/dragonflow/devstack/zookeeper_driver
    NB_DRIVER_CLASS="dragonflow.db.drivers.zookeeper_db_driver.ZookeeperDbDriver"
fi

# Pub/Sub Service
#----------------
# To be called to initialise params common to all pubsub drivers
function init_pubsub {
    enable_service df-publisher-service
    DF_PUB_SUB="True"
}

if is_service_enabled df-zmq-publisher-service ; then
    init_pubsub
    source $DEST/dragonflow/devstack/zmq_pubsub_driver
fi

# Dragonflow installation uses functions from these files
source $TOP_DIR/lib/neutron_plugins/ovs_base
source $TOP_DIR/lib/neutron_plugins/openvswitch_agent

# Entry Points
# ------------

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

    local _pwd=$(pwd)
    cd $DEST/$OVS_REPO_NAME
    sudo make uninstall
    cd $_pwd
}

function configure_df_plugin {
    echo "Configuring Neutron for Dragonflow"

    if is_service_enabled q-svc ; then
        export NETWORK_API_EXTENSIONS='binding,quotas,agent,dhcp_agent_scheduler,external-net,router'
        Q_PLUGIN_CLASS="dragonflow.neutron.plugin.DFPlugin"

        NEUTRON_CONF=/etc/neutron/neutron.conf
        iniset $NEUTRON_CONF df remote_db_ip "$REMOTE_DB_IP"
        iniset $NEUTRON_CONF df remote_db_port $REMOTE_DB_PORT
        iniset $NEUTRON_CONF df remote_db_hosts "$REMOTE_DB_HOSTS"
        iniset $NEUTRON_CONF df nb_db_class "$NB_DRIVER_CLASS"
        iniset $NEUTRON_CONF df local_ip "$HOST_IP"
        iniset $NEUTRON_CONF df tunnel_type "$TUNNEL_TYPE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
        iniset $NEUTRON_CONF df monitor_table_poll_time "$DF_MONITOR_TABLE_POLL_TIME"
        iniset $NEUTRON_CONF df_l2_app l2_responder "$DF_L2_RESPONDER"
        iniset $NEUTRON_CONF df enable_df_pub_sub "$DF_PUB_SUB"
        iniset $NEUTRON_CONF df pub_sub_use_multiproc "$DF_PUB_SUB_USE_MULTIPROC"
        iniset $NEUTRON_CONF df publishers_ips "$PUBLISHERS_HOSTS"
        iniset $NEUTRON_CONF DEFAULT advertise_mtu "True"
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""

        if is_service_enabled q-dhcp ; then
            iniset $NEUTRON_CONF df use_centralized_ipv6_DHCP "True"
        else
            iniset $NEUTRON_CONF DEFAULT dhcp_agent_notification "False"
        fi
    else
        _create_neutron_conf_dir
        # NOTE: We need to manually generate the neutron.conf file here. This
        #       is normally done by a call to _configure_neutron_common in
        #       neutron-lib, but we don't call that for compute nodes here.
        # Uses oslo config generator to generate core sample configuration files
        local _pwd=$(pwd)
        NEUTRON_CONF=/etc/neutron/neutron.conf
        (cd $NEUTRON_DIR && exec ./tools/generate_config_file_samples.sh)
        cd $_pwd

        cp $NEUTRON_DIR/etc/neutron.conf.sample $NEUTRON_CONF

        iniset $NEUTRON_CONF df remote_db_ip "$REMOTE_DB_IP"
        iniset $NEUTRON_CONF df remote_db_port $REMOTE_DB_PORT
        iniset $NEUTRON_CONF df remote_db_hosts "$REMOTE_DB_HOSTS"
        iniset $NEUTRON_CONF df nb_db_class "$NB_DRIVER_CLASS"
        iniset $NEUTRON_CONF df local_ip "$HOST_IP"
        iniset $NEUTRON_CONF df tunnel_type "$TUNNEL_TYPE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
        iniset $NEUTRON_CONF df_l2_app l2_responder "$DF_L2_RESPONDER"
        iniset $NEUTRON_CONF df enable_df_pub_sub "$DF_PUB_SUB"
        iniset $NEUTRON_CONF df publishers_ips "$PUBLISHERS_HOSTS"
    fi
}

# init_ovs() - Initialize databases, etc.
function init_ovs {
    # clean up from previous (possibly aborted) runs
    # create required data files

    # Assumption: this is a dedicated test system and there is nothing important
    #  ovs databases.  We're going to trash them and
    # create new ones on each devstack run.

    base_dir=$DATA_DIR/ovs
    mkdir -p $base_dir

    for db in conf.db  ; do
        if [ -f $base_dir/$db ] ; then
            rm -f $base_dir/$db
        fi
    done
    rm -f $base_dir/.*.db.~lock~

    echo "Creating OVS Database"
    ovsdb-tool create $base_dir/conf.db $DEST/$OVS_REPO_NAME/vswitchd/vswitch.ovsschema
}

function install_zeromq {
    if is_fedora; then
        install_package zeromq python-zmq
    elif is_ubuntu; then
        install_package libzmq1 python-zmq
    elif is_suse; then
        install_package libzmq1 python-pyzmq
    fi
    # Necessary directory for socket location.
    sudo mkdir -p /var/run/openstack
    sudo chown $STACK_USER /var/run/openstack
}

function install_df {

    # Obtain devstack directory for df-ext-services.sh
    sed -i "/^TOP_DIR=/cTOP_DIR=$TOP_DIR" $DEST/dragonflow/devstack/df-ext-services.sh

    install_zeromq

    nb_db_driver_install_server

    nb_db_driver_install_client

    #echo_summary "Installing DragonFlow"
    #git clone $DRAGONFLOW_REPO $DRAGONFLOW_DIR $DRAGONFLOW_BRANCH
    setup_package $DRAGONFLOW_DIR
}

# install_ovs() - Collect source and prepare
function install_ovs {
    echo "Installing OVS and dependent packages"

    # If OVS is already installed, remove it, because we're about to re-install
    # it from source.
    for package in openvswitch openvswitch-switch openvswitch-common; do
        if is_package_installed $package ; then
            uninstall_package $package
        fi
    done

    if ! is_neutron_enabled ; then
        install_neutron
    fi

    install_package python-openvswitch
    source $NEUTRON_DIR/devstack/lib/ovs
    compile_ovs True
    sudo chown $(whoami) /usr/local/var/run/openvswitch
    sudo chown $(whoami) /usr/local/var/log/openvswitch
}

# stop_ovs_dp() - Stop OVS datapath
function stop_ovs_dp {
    sudo ovs-dpctl dump-dps | sudo xargs -n1 ovs-dpctl del-dp
    sudo rmmod vport_geneve
    sudo rmmod openvswitch
}

function stop_ovs
{
    # Stop ovs db
    ovs_service_stop $OVS_DB_SERVICE
    # Stop ovs vswitch
    ovs_service_stop $OVS_VSWITCHD_SERVICE

    while ovs_service_status $OVS_DB_SERVICE; do
        echo "Waiting for the $OVS_DB_SERVICE to be stopped..."
        sleep 1
        ovs_service_stop $OVS_DB_SERVICE
    done

    while ovs_service_status $OVS_VSWITCHD_SERVICE; do
        echo "Waiting for the ovsdb-vswitchd to be stopped..."
        sleep 1
        ovs_service_stop $OVS_VSWITCHD_SERVICE
    done
}

# The following returns "0" when service is live.
# Zero (0) is considered a TRUE value in bash.
function ovs_service_status
{
    TEMP_PID=$OVS_DIR"/"$1".pid"
    if [ -e $TEMP_PID ]
    then
        TEMP_PID_VALUE=$(cat $TEMP_PID  2>/dev/null)
        if [ -e /proc/$TEMP_PID_VALUE ]
        then
            return 0
        fi
    fi
    # service is dead
    return 1
}

# Kills a service
function ovs_service_stop
{
    TEMP_PID=$OVS_DIR"/"$1".pid"
    if [ -e $TEMP_PID ]
    then
        TEMP_PID_VALUE=$(cat $TEMP_PID  2>/dev/null)
        if [ -e /proc/$TEMP_PID_VALUE ]
        then
            sudo kill $TEMP_PID_VALUE
        fi
    fi
}

function start_ovs {
    echo "Starting OVS"

    local _pwd=$(pwd)
    cd $DATA_DIR/ovs

    EXTRA_DBS=""
    OVSDB_REMOTE="--remote=ptcp:6640:$HOST_IP"

    if ! ovs_service_status $OVS_DB_SERVICE; then
        #echo "Going to start $OVS_DB_SERVICE"
        $OVS_DB_SERVICE --remote=punix:$OVS_DIR"/db.sock" \
                --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
                --pidfile=$OVS_DB_PID --detach -vconsole:off --log-file $OVSDB_REMOTE \
                conf.db ${EXTRA_DBS}

        echo -n "Waiting for $OVS_DB_SERVICE to start ... "
        while ! test -e $OVS_DIR"/db.sock" ; do
            sleep 1
        done
        echo "done."
        ovs-vsctl --no-wait init
    fi

    if is_service_enabled df-controller ; then
        if ! ovs_service_status $OVS_VSWITCHD_SERVICE; then
            #echo "Going to start $OVS_VSWITCHD_SERVICE"
            sudo modprobe openvswitch || die $LINENO "Failed to load openvswitch module"
            # TODO This needs to be a fatal error when doing multi-node testing, but
            # breaks testing in OpenStack CI where geneve isn't available.
            #sudo modprobe geneve || die $LINENO "Failed to load geneve module"
            sudo modprobe geneve || true
            #sudo modprobe vport_geneve || die $LINENO "Failed to load vport_geneve module"
            sudo modprobe vport_geneve || true

            _neutron_ovs_base_setup_bridge br-int
            ovs-vsctl --no-wait set bridge br-int fail-mode=secure other-config:disable-in-band=true

            sudo $OVS_VSWITCHD_SERVICE --pidfile=$OVS_VSWITCHD_PID --detach -vconsole:off --log-file
        fi
    fi

    cd $_pwd
}

# start_df() - Start running processes, including screen
function start_df {
    echo "Starting Dragonflow"

    if is_service_enabled df-controller ; then
        ovs-vsctl --no-wait set-controller br-int tcp:$HOST_IP:6633
        run_process df-controller "python $DF_LOCAL_CONTROLLER --config-file $NEUTRON_CONF"
        run_process df-ext-services "bash $DEST/dragonflow/devstack/df-ext-services.sh"
    fi
}

# stop_df() - Stop running processes (non-screen)
function stop_df {
    if is_service_enabled df-controller ; then
        stop_process df-controller
        ovs_service_stop $OVS_VSWITCHD_SERVICE
    fi

    nb_db_driver_stop_server

    ovs_service_stop $OVS_DB_SERVICE
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

function verify_ryu_version {
    # Verify ryu is installed. Version greater than 3.29. Does not return
    # on failure.
    RYU_VER_LINE=`ryu --version 2>&1 | head -n 1`
    RYU_VER=`echo $RYU_VER_LINE | cut -d' ' -f2`
    echo "Found ryu version $RYU_VER ($RYU_VER_LINE)"
    if [ `vercmp_numbers "$RYU_VER" "3.29.1"` -lt 0 ]; then
        die $LINENO "ryu version $RYU_VER too low. Version 3.29.1+ is required for Dragonflow."
    fi
}

function start_pubsub_service {
    PUBLISHER_SERVICE=$DRAGONFLOW_DIR/dragonflow/controller/df_publisher_service.py
    set python $PUBLISHER_SERVICE
    set "$@" --config-file $NEUTRON_CONF
    run_process df-publisher-service "$*"
}

function stop_pubsub_service {
    stop_process df-publisher-service
}

# main loop
if [[ "$Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        if [[ "$OFFLINE" != "True" ]]; then
            install_df
            install_ovs
        fi
        echo export PYTHONPATH=\$PYTHONPATH:$DRAGONFLOW_DIR >> $RC_DIR/.localrc.auto
        init_ovs
        # We have to start at install time, because Neutron's post-config
        # phase runs ovs-vsctl.
        nb_db_driver_start_server
        start_ovs
        disable_libvirt_apparmor
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        configure_df_plugin
        if [[ "$DF_PUB_SUB" == "True" ]]; then
            # Implemented by the pub/sub plugin
            configure_pubsub_service_plugin
            # Defaults, in case no Pub/Sub service was selected
            if [ -z $PUB_SUB_DRIVER ]; then
                die $LINENO "pub-sub enabled, but no pub-sub driver selected"
            fi
            PUB_SUB_MULTIPROC_DRIVER=${PUB_SUB_MULTIPROC_DRIVER:-$PUB_SUB_DRIVER}
        fi

        if is_service_enabled nova; then
            create_nova_conf_neutron
        fi

        if is_service_enabled df-publisher-service; then
            start_pubsub_service
        fi
        start_df
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_df
        stop_ovs_dp
        cleanup_ovs
        if [[ "$DF_PUB_SUB" == "True" ]]; then
            stop_pubsub_service
        fi
    fi
fi
