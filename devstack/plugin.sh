# dragonflow.sh - Devstack extras script to install Dragonflow

# By default, dragonflow uses DFPlugin as core plugin. If you want to use
# ML2 as core plugin, you can edit local.conf file to configure
# "USE_ML2_PLUGIN=True" and "Q_ML2_PLUGIN_MECHANISM_DRIVERS=df"
# if you want to use df-l3 as the l3 services plugin, you could edit
# local.conf file to configure "ML2_L3_PLUGIN=df-l3"
USE_ML2_PLUGIN=${USE_ML2_PLUGIN:-"False"}

# Enable DPDK for Open vSwitch user space datapath
ENABLE_DPDK=${ENABLE_DPDK:-False}
DPDK_NUM_OF_HUGEPAGES=${DPDK_NUM_OF_HUGEPAGES:-1024}
DPDK_BIND_DRIVER=${DPDK_BIND_DRIVER:-igb_uio}
DPDK_NIC_NAME=${DPDK_NIC_NAME:-eth1}

# The git repo to use
OVS_REPO=${OVS_REPO:-http://github.com/openvswitch/ovs.git}
OVS_REPO_NAME=$(basename ${OVS_REPO} | cut -f1 -d'.')

# The branch to use from $OVS_REPO
# TODO(gsagie) Currently take branch-2.5 branch as master is not stable
OVS_BRANCH=${OVS_BRANCH:-branch-2.5}

DEFAULT_TUNNEL_TYPE="geneve"
DEFAULT_APPS_LIST="l2_app.L2App,l3_proactive_app.L3ProactiveApp,"\
"dhcp_app.DHCPApp,dnat_app.DNATApp,sg_app.SGApp,portsec_app.PortSecApp"
ML2_APPS_LIST_DEFAULT="l2_ml2_app.L2App,l3_proactive_app.L3ProactiveApp,"\
"dhcp_app.DHCPApp,dnat_app.DNATApp,sg_app.SGApp,portsec_app.PortSecApp"

if is_service_enabled df-metadata ; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,metadata_service_app.MetadataServiceApp"
    ML2_APPS_LIST_DEFAULT="$ML2_APPS_LIST_DEFAULT,metadata_service_app.MetadataServiceApp"
fi

DF_APPS_LIST=${DF_APPS_LIST:-$DEFAULT_APPS_LIST}
ML2_APPS_LIST=${ML2_APPS_LIST:-$ML2_APPS_LIST_DEFAULT}
TUNNEL_TYPE=${TUNNEL_TYPE:-$DEFAULT_TUNNEL_TYPE}

# How to connect to the database storing the virtual topology.
REMOTE_DB_IP=${REMOTE_DB_IP:-$HOST_IP}
REMOTE_DB_PORT=${REMOTE_DB_PORT:-4001}
REMOTE_DB_HOSTS=${REMOTE_DB_HOSTS:-"$REMOTE_DB_IP:$REMOTE_DB_PORT"}

# OVS bridge definition
PUBLIC_BRIDGE=${PUBLIC_BRIDGE:-br-ex}
INTEGRATION_BRIDGE=${INTEGRATION_BRIDGE:-br-int}
INTEGRATION_PEER_PORT=${INTEGRATION_PEER_PORT:-patch-ex}
PUBLIC_PEER_PORT=${PUBLIC_PEER_PORT:-patch-int}

# OVS related pid files
#----------------------
OVS_DB_SERVICE="ovsdb-server"
OVS_VSWITCHD_SERVICE="ovs-vswitchd"
OVS_DIR="/var/run/openvswitch"
OVS_DB_PID=$OVS_DIR"/"$OVS_DB_SERVICE".pid"
OVS_VSWITCHD_PID=$OVS_DIR"/"$OVS_VSWITCHD_SERVICE".pid"
OVS_VSWITCH_OCSSCHEMA_FILE=${OVS_VSWITCH_OCSSCHEMA_FILE:-"/usr/share/openvswitch/vswitch.ovsschema"}

ACTION=$1
STAGE=$2

# Pluggable DB drivers
#----------------------
function is_df_db_driver_selected {
    if [[ "$ACTION" == "stack" && "$STAGE" == "pre-install" ]]; then
        test -n "$NB_DRIVER_CLASS"
        return $?
    fi
    return 1
}

if is_service_enabled df-etcd ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/etcd_driver
    NB_DRIVER_CLASS="etcd_nb_db_driver"
fi
if is_service_enabled df-ramcloud ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/ramcloud_driver
    NB_DRIVER_CLASS="ramcloud_nb_db_driver"
fi
if is_service_enabled df-zookeeper ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/zookeeper_driver
    NB_DRIVER_CLASS="zookeeper_nb_db_driver"
fi
if is_service_enabled df-redis ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/redis_driver
    NB_DRIVER_CLASS="redis_nb_db_driver"
    DF_REDIS_PUBSUB=${DF_REDIS_PUBSUB:-"True"}
else
    DF_REDIS_PUBSUB="False"
fi

# As the function returns actual value only on pre-install, ignore it on later stages
if [[ "$ACTION" == "stack" && "$STAGE" == "pre-install" ]]; then
    is_df_db_driver_selected || die $LINENO "No database service is set for Dragonflow."
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

if [[ "$DF_REDIS_PUBSUB" == "True" ]]; then
    DF_PUB_SUB="True"
    DF_PUB_SUB_USE_MULTIPROC="False"
    source $DEST/dragonflow/devstack/redis_pubsub_driver
fi

# Dragonflow installation uses functions from these files
source $TOP_DIR/lib/neutron_plugins/ovs_base

if [[ "$ENABLE_DPDK" == "True" ]]; then
    source $DEST/dragonflow/devstack/ovs_dpdk_setup.sh
else
    source $DEST/dragonflow/devstack/ovs_setup.sh
fi

# Entry Points
# ------------

function configure_df_metadata_service {
    if is_service_enabled df-metadata ; then
        NOVA_CONF=${NOVA_CONF:-"/etc/nova/nova.conf"}
        iniset $NOVA_CONF neutron service_metadata_proxy True
        iniset $NOVA_CONF neutron metadata_proxy_shared_secret $METADATA_PROXY_SHARED_SECRET
        iniset $NEUTRON_CONF DEFAULT metadata_proxy_shared_secret $METADATA_PROXY_SHARED_SECRET
        iniset $NEUTRON_CONF df_metadata ip "$DF_METADATA_SERVICE_IP"
        iniset $NEUTRON_CONF df_metadata port "$DF_METADATA_SERVICE_PORT"
        iniset $NEUTRON_CONF df metadata_interface "$DF_METADATA_SERVICE_INTERFACE"
    fi
}

function configure_df_plugin {
    echo "Configuring Neutron for Dragonflow"

    if is_service_enabled q-svc ; then

        # NOTE(gsagie) needed for tempest
        export NETWORK_API_EXTENSIONS=$(python -c \
            'from dragonflow.common import extensions ;\
             print ",".join(extensions.SUPPORTED_API_EXTENSIONS)')

        if [[ "$USE_ML2_PLUGIN" == "False" ]]; then
            Q_PLUGIN_CLASS="dragonflow.neutron.plugin.DFPlugin"
            Q_SERVICE_PLUGIN_CLASSES=""
        else
            DF_APPS_LIST=$ML2_APPS_LIST
        fi

        NEUTRON_CONF=/etc/neutron/neutron.conf
        iniset $NEUTRON_CONF df remote_db_ip "$REMOTE_DB_IP"
        iniset $NEUTRON_CONF df remote_db_port $REMOTE_DB_PORT
        iniset $NEUTRON_CONF df remote_db_hosts "$REMOTE_DB_HOSTS"
        iniset $NEUTRON_CONF df nb_db_class "$NB_DRIVER_CLASS"
        iniset $NEUTRON_CONF df local_ip "$HOST_IP"
        iniset $NEUTRON_CONF df tunnel_type "$TUNNEL_TYPE"
        iniset $NEUTRON_CONF df integration_bridge "$INTEGRATION_BRIDGE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
        iniset $NEUTRON_CONF df monitor_table_poll_time "$DF_MONITOR_TABLE_POLL_TIME"
        iniset $NEUTRON_CONF df_l2_app l2_responder "$DF_L2_RESPONDER"
        iniset $NEUTRON_CONF df enable_df_pub_sub "$DF_PUB_SUB"
        iniset $NEUTRON_CONF df pub_sub_use_multiproc "$DF_PUB_SUB_USE_MULTIPROC"
        iniset $NEUTRON_CONF df publisher_rate_limit_timeout "$PUBLISHER_RATE_LIMIT_TIMEOUT"
        iniset $NEUTRON_CONF df publisher_rate_limit_count "$PUBLISHER_RATE_LIMIT_COUNT"
        iniset $NEUTRON_CONF df_dnat_app external_network_bridge "$PUBLIC_BRIDGE"
        iniset $NEUTRON_CONF df_dnat_app int_peer_patch_port "$INTEGRATION_PEER_PORT"
        iniset $NEUTRON_CONF df_dnat_app ex_peer_patch_port "$PUBLIC_PEER_PORT"
        iniset $NEUTRON_CONF DEFAULT advertise_mtu "True"
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins "$Q_SERVICE_PLUGIN_CLASSES"

        if is_service_enabled q-dhcp ; then
            iniset $NEUTRON_CONF df use_centralized_ipv6_DHCP "True"
        else
            iniset $NEUTRON_CONF DEFAULT dhcp_agent_notification "False"
        fi

        if [[ "$DF_PUB_SUB" == "True" ]]; then
            DF_SELECTIVE_TOPO_DIST=${DF_SELECTIVE_TOPO_DIST:-"True"}
        else
            DF_SELECTIVE_TOPO_DIST="False"
        fi
        iniset $NEUTRON_CONF df enable_selective_topology_distribution \
                                "$DF_SELECTIVE_TOPO_DIST"

        if [[ "$DF_RUNNING_IN_GATE" == "True" ]]; then
            iniset $NEUTRON_CONF quotas default_quota "-1"
            iniset $NEUTRON_CONF quotas quota_network "-1"
            iniset $NEUTRON_CONF quotas quota_subnet "-1"
            iniset $NEUTRON_CONF quotas quota_port "-1"
            iniset $NEUTRON_CONF quotas quota_router "-1"
            iniset $NEUTRON_CONF quotas quota_floatingip "-1"
            iniset $NEUTRON_CONF quotas quota_security_group_rule "-1"
        fi

        configure_df_metadata_service
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
        iniset $NEUTRON_CONF df integration_bridge "$INTEGRATION_BRIDGE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
        iniset $NEUTRON_CONF df_l2_app l2_responder "$DF_L2_RESPONDER"
        iniset $NEUTRON_CONF df enable_df_pub_sub "$DF_PUB_SUB"
        iniset $NEUTRON_CONF df_dnat_app external_network_bridge "$PUBLIC_BRIDGE"
        iniset $NEUTRON_CONF df_dnat_app int_peer_patch_port "$INTEGRATION_PEER_PORT"
        iniset $NEUTRON_CONF df_dnat_app ex_peer_patch_port "$PUBLIC_PEER_PORT"

        if [[ "$DF_PUB_SUB" == "True" ]]; then
            DF_SELECTIVE_TOPO_DIST=${DF_SELECTIVE_TOPO_DIST:-"True"}
        else
            DF_SELECTIVE_TOPO_DIST="False"
        fi
        iniset $NEUTRON_CONF df enable_selective_topology_distribution \
                                "$DF_SELECTIVE_TOPO_DIST"
        configure_df_metadata_service
    fi
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

    if function_exists nb_db_driver_install_server; then
        nb_db_driver_install_server
    fi

    if function_exists nb_db_driver_install_client; then
        nb_db_driver_install_client
    fi

    setup_package $DRAGONFLOW_DIR
}

# The following returns "0" when service is live.
# Zero (0) is considered a TRUE value in bash.
function ovs_service_status
{
    TEMP_PID=$OVS_DIR"/"$1".pid"
    if [ -e $TEMP_PID ]
    then
        TEMP_PID_VALUE=$(cat $TEMP_PID 2>/dev/null)
        if [ -e /proc/$TEMP_PID_VALUE ]
        then
            return 0
        fi
    fi
    # service is dead
    return 1
}

function is_module_loaded {
    return $(lsmod | grep -q $1)
}

function load_module_if_not_loaded {
    local module=$1
    local fatal=$2

    if is_module_loaded $module; then
        echo "Module already loaded: $module"
    else
        if [ "$(trueorfalse True fatal)" == "True" ]; then
            sudo modprobe $module || (die $LINENO "FAILED TO LOAD $module")
        else
            sudo modprobe $module || (echo "FAILED TO LOAD $module")
        fi
    fi
}

function unload_module_if_loaded {
    local module=$1

    if is_module_loaded $module; then
        sudo rmmod $module || (die $LINENO "FAILED TO UNLOAD $module")
    else
        echo "Module is not loaded: $module"
    fi
}

# cleanup_nb_db() - Clean all the keys in the northbound database
function cleanup_nb_db {
    # clean db only on the master node
    if is_service_enabled q-svc ; then
        if [[ "$DF_Q_SVC_MASTER" == "True" ]]; then
            df-db clean
        fi
    fi
}

# init_nb_db() - Create all the tables in northbound database
function init_nb_db {
    # init db only on the master node
    if is_service_enabled q-svc ; then
        if [[ "$DF_Q_SVC_MASTER" == "True" ]]; then
            df-db init
        fi
    fi
}

# drop_nb_db() - Drop all the tables in northbound database
function drop_nb_db {
    # drop db only on the master node
    if is_service_enabled q-svc ; then
        if [[ "$DF_Q_SVC_MASTER" == "True" ]]; then
            df-db dropall
        fi
    fi
}

# start_df() - Start running processes, including screen
function start_df {
    echo "Starting Dragonflow"

    if is_service_enabled df-controller ; then
        sudo ovs-vsctl --no-wait set-controller $INTEGRATION_BRIDGE tcp:127.0.0.1:6633
        run_process df-controller "$DF_LOCAL_CONTROLLER_BINARY --config-file $NEUTRON_CONF"
        run_process df-ext-services "bash $DEST/dragonflow/devstack/df-ext-services.sh"
    fi
}

# stop_df() - Stop running processes (non-screen)
function stop_df {
    if is_service_enabled df-controller ; then
        stop_process df-controller
    fi

    cleanup_nb_db
    drop_nb_db

    if function_exists nb_db_driver_stop_server; then
        nb_db_driver_stop_server
    fi
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
    echo "Starting Dragonflow publisher service"
    if is_service_enabled df-publisher-service ; then
        run_process df-publisher-service "$DF_PUBLISHER_SERVICE_BINARY --config-file $NEUTRON_CONF"
    fi
}

function stop_pubsub_service {
    if is_service_enabled df-publisher-service ; then
        stop_process df-publisher-service
    fi
}

function start_df_metadata_agent {
    if is_service_enabled df-metadata ; then
        echo "Starting Dragonflow metadata service"
        run_process df-metadata "python $DF_METADATA_SERVICE --config-file $NEUTRON_CONF"
    fi
}

function stop_df_metadata_agent {
    if is_service_enabled df-metadata ; then
        echo "Stopping Dragonflow metadata service"
        stop_process df-metadata
        sudo ovs-vsctl del-port br-int $DF_METADATA_SERVICE_INTERFACE
    fi
}

# main loop
if [[ "$Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        if [[ "$OFFLINE" != "True" ]]; then
            if ! is_neutron_enabled ; then
                install_neutron
            fi
            install_df
            install_ovs
        fi
        setup_develop $DRAGONFLOW_DIR
        init_ovs
        # We have to start at install time, because Neutron's post-config
        # phase runs ovs-vsctl.
        start_ovs
        if function_exists nb_db_driver_start_server; then
            nb_db_driver_start_server
        fi
        disable_libvirt_apparmor
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        configure_ovs
        configure_df_plugin
        # initialize the nb db
        init_nb_db

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
        start_df_metadata_agent
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_df_metadata_agent
        stop_df
        cleanup_ovs
        stop_ovs
        uninstall_ovs
        if is_service_enabled df-publisher-service; then
            stop_pubsub_service
        fi
    fi
fi
