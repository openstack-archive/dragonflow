#@IgnoreInspection BashAddShebang
# dragonflow.sh - Devstack extras script to install Dragonflow

# Enable DPDK for Open vSwitch user space datapath
ENABLE_DPDK=${ENABLE_DPDK:-False}
DPDK_NUM_OF_HUGEPAGES=${DPDK_NUM_OF_HUGEPAGES:-1024}
DPDK_BIND_DRIVER=${DPDK_BIND_DRIVER:-igb_uio}
DPDK_NIC_NAME=${DPDK_NIC_NAME:-eth1}

# The git repo to use
OVS_REPO=${OVS_REPO:-https://github.com/openvswitch/ovs.git}
OVS_REPO_NAME=$(basename ${OVS_REPO} | cut -f1 -d'.')

# The branch to use from $OVS_REPO
OVS_BRANCH=${OVS_BRANCH:-branch-2.6}

# Set empty EXTERNAL_HOST_IP
EXTERNAL_HOST_IP=${EXTERNAL_HOST_IP:-}

DEFAULT_TUNNEL_TYPES="vxlan,geneve,gre"
DEFAULT_APPS_LIST="portbinding,l2,l3_proactive,dhcp,dnat,sg,portqos,classifier,tunneling,provider"

if [[ $ENABLE_DF_SFC == "True" ]]; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,fc,sfc"
fi

if is_service_enabled df-metadata ; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,metadata_service"
fi

if is_service_enabled q-trunk ; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,trunk"
fi

ENABLE_ACTIVE_DETECTION=${ENABLE_ACTIVE_DETECTION:-True}
if [[ "$ENABLE_ACTIVE_DETECTION" == "True" ]]; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,active_port_detection"
fi

ENABLE_LIVE_MIGRATION=${ENABLE_LIVE_MIGRATION:-True}
if [[ "$ENABLE_LIVE_MIGRATION" == "True" ]]; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,migration"
fi

if [[ ! -z ${EXTERNAL_HOST_IP} ]]; then
    DEFAULT_APPS_LIST="$DEFAULT_APPS_LIST,chassis_snat"
fi

ENABLED_AGING_APP=${ENABLE_AGING_APP:-True}
if [[ "$ENABLE_AGING_APP" == "True" ]]; then
    DEFAULT_APPS_LIST="aging,$DEFAULT_APPS_LIST"
fi

if is_service_enabled df-skydive ; then
    SKYDIVE_ENDPOINT=${SKYDIVE_ENDPOINT:-$SERVICE_HOST:8082}
fi

DF_APPS_LIST=${DF_APPS_LIST:-$DEFAULT_APPS_LIST}
TUNNEL_TYPES=${TUNNEL_TYPE:-$DEFAULT_TUNNEL_TYPES}

# OVS related pid files
#----------------------
OVS_DB_SERVICE="ovsdb-server"
OVS_VSWITCHD_SERVICE="ovs-vswitchd"
OVS_DIR="/var/run/openvswitch"
OVS_DB_PID=$OVS_DIR"/"$OVS_DB_SERVICE".pid"
OVS_VSWITCHD_PID=$OVS_DIR"/"$OVS_VSWITCHD_SERVICE".pid"
OVS_VSWITCH_OCSSCHEMA_FILE=${OVS_VSWITCH_OCSSCHEMA_FILE:-"/usr/share/openvswitch/vswitch.ovsschema"}

# Neutron notifier
ENABLE_NEUTRON_NOTIFIER=${ENABLE_NEUTRON_NOTIFIER:-"False"}

# Set value of TUNNEL_ENDPOINT_IP if unset
TUNNEL_ENDPOINT_IP=${TUNNEL_ENDPOINT_IP:-$HOST_IP}

ENABLE_DF_SFC=${ENABLE_DF_SFC:-"False"}
if [[ $ENABLE_DF_SFC == "True" ]]; then
    NEUTRON_SFC_DRIVERS=dragonflow
    NEUTRON_FLOWCLASSIFIER_DRIVERS=dragonflow
fi

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
    REMOTE_DB_PORT=${REMOTE_DB_PORT:-2379}
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

if is_service_enabled df-cassandra ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/cassandra_driver
    NB_DRIVER_CLASS="cassandra_nb_db_driver"
fi

if is_service_enabled df-rethinkdb ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/rethinkdb_driver
    NB_DRIVER_CLASS="rethinkdb_nb_db_driver"
fi

if is_service_enabled df-redis ; then
    is_df_db_driver_selected && die $LINENO "More than one database service is set for Dragonflow."
    source $DEST/dragonflow/devstack/redis_driver
    NB_DRIVER_CLASS="redis_nb_db_driver"
    DF_REDIS_PUBSUB=${DF_REDIS_PUBSUB:-"True"}
else
    DF_REDIS_PUBSUB="False"
fi

# How to connect to the database storing the virtual topology.
REMOTE_DB_IP=${REMOTE_DB_IP:-$HOST_IP}
REMOTE_DB_PORT=${REMOTE_DB_PORT:-4001}
REMOTE_DB_HOSTS=${REMOTE_DB_HOSTS:-"$REMOTE_DB_IP:$REMOTE_DB_PORT"}

# As the function returns actual value only on pre-install, ignore it on later stages
if [[ "$ACTION" == "stack" && "$STAGE" == "pre-install" ]]; then
    is_df_db_driver_selected || die $LINENO "No database service is set for Dragonflow."
fi

# Pub/Sub Service
#----------------
# To be called to initialise params common to all pubsub drivers
function init_pubsub {
    DF_PUB_SUB="True"
}

if is_service_enabled df-zmq-publisher-service ; then
    init_pubsub
    enable_service df-publisher-service
    source $DEST/dragonflow/devstack/zmq_pubsub_driver
fi

if is_service_enabled df-etcd-pubsub-service ; then
    init_pubsub
    source $DEST/dragonflow/devstack/etcd_pubsub_driver
fi

if [[ "$DF_REDIS_PUBSUB" == "True" ]]; then
    init_pubsub
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
        iniset $DRAGONFLOW_CONF df_metadata ip "$DF_METADATA_SERVICE_IP"
        iniset $DRAGONFLOW_CONF df_metadata port "$DF_METADATA_SERVICE_PORT"
        iniset $DRAGONFLOW_CONF df_metadata metadata_interface "$DF_METADATA_SERVICE_INTERFACE"
        pushd $DRAGONFLOW_DIR
        # TODO(snapiri) When we add more switch backends, this should be conditional
        tools/ovs_metadata_service_deployment.sh install $INTEGRATION_BRIDGE $DF_METADATA_SERVICE_INTERFACE $DF_METADATA_SERVICE_IP $DF_METADATA_SERVICE_PORT
        popd
    fi
}

function configure_qos {
    Q_SERVICE_PLUGIN_CLASSES+=",qos"
    Q_ML2_PLUGIN_EXT_DRIVERS+=",qos"
    iniset /$Q_PLUGIN_CONF_FILE ml2 extension_drivers "$Q_ML2_PLUGIN_EXT_DRIVERS"
}

function configure_trunk {
    Q_SERVICE_PLUGIN_CLASSES+=",trunk"
    Q_ML2_PLUGIN_EXT_DRIVERS+=",trunk"
    iniset /$Q_PLUGIN_CONF_FILE ml2 extension_drivers "$Q_ML2_PLUGIN_EXT_DRIVERS"
}

function configure_bgp {
    setup_develop $DEST/neutron-dynamic-routing
    _neutron_service_plugin_class_add df-bgp
    # Since we are using a plugin outside neutron-dynamic-routing, we need to
    # specify api_extensions_path explicitly.
    iniset $NEUTRON_CONF DEFAULT api_extensions_path "$DEST/neutron-dynamic-routing/neutron_dynamic_routing/extensions"
}

function configure_sfc {
    setup_develop $DEST/networking-sfc
}

function init_neutron_sample_config {
    # NOTE: We must make sure that neutron config file exists before
    # going further with ovs setup
    if [ ! -f $NEUTRON_CONF ] ; then
        sudo install -d -o $STACK_USER $NEUTRON_CONF_DIR
        pushd $NEUTRON_DIR
        tools/generate_config_file_samples.sh
        popd
        cp $NEUTRON_DIR/etc/neutron.conf.sample $NEUTRON_CONF
    fi
}

function configure_df_skydive {
    iniset $DRAGONFLOW_CONF df_skydive analyzer_endpoint "$SKYDIVE_ENDPOINT"
    if [[ -n "$DF_SKYDIVE_USER" ]]; then
        iniset $DRAGONFLOW_CONF df_skydive user "$DF_SKYDIVE_USER"
    fi
    local DF_SKYDIVE_PASSWORD=${DF_SKYDIVE_PASSWORD:-$ADMIN_PASSWORD}
    iniset $DRAGONFLOW_CONF df_skydive password "$DF_SKYDIVE_PASSWORD"
    if [[ -n "$DF_SKYDIVE_UPDATE_INTERVAL" ]]; then
        iniset $DRAGONFLOW_CONF df_skydive update_interval "$DF_SKYDIVE_UPDATE_INTERVAL"
    fi
}


function configure_df_plugin {
    echo "Configuring Neutron for Dragonflow"

    # Generate DF config file
    pushd $DRAGONFLOW_DIR
    tools/generate_config_file_samples.sh
    popd
    mkdir -p $Q_PLUGIN_EXTRA_CONF_PATH
    sudo mkdir -p /var/run/dragonflow
    sudo chown $STACK_USER /var/run/dragonflow
    cp $DRAGONFLOW_DIR/etc/dragonflow.ini.sample $DRAGONFLOW_CONF
    cp $DRAGONFLOW_DIR/etc/dragonflow_datapath_layout.yaml $DRAGONFLOW_DATAPATH

    if is_service_enabled q-svc ; then
        if is_service_enabled q-qos ; then
            configure_qos
        fi

        if [[ "$DR_MODE" == "df-bgp" ]]; then
            configure_bgp
        fi

        if is_service_enabled q-trunk ; then
            configure_trunk
        fi

        if [[ "$ENABLE_DF_SFC" == "True" ]]; then
            configure_sfc
        fi

        # NOTE(gsagie) needed for tempest
        export NETWORK_API_EXTENSIONS=$(python -c \
            'from dragonflow.common import extensions ;\
             print ",".join(extensions.SUPPORTED_API_EXTENSIONS)')

        # Set netron-server related settings
        iniset $DRAGONFLOW_CONF df monitor_table_poll_time "$DF_MONITOR_TABLE_POLL_TIME"
        iniset $DRAGONFLOW_CONF df publisher_rate_limit_timeout "$PUBLISHER_RATE_LIMIT_TIMEOUT"
        iniset $DRAGONFLOW_CONF df publisher_rate_limit_count "$PUBLISHER_RATE_LIMIT_COUNT"
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins "$Q_SERVICE_PLUGIN_CLASSES"

        iniset $DRAGONFLOW_CONF df auto_detect_port_behind_port "$DF_AUTO_DETECT_PORT_BEHIND_PORT"
        iniset $DRAGONFLOW_CONF df_loadbalancer auto_enable_vip_ports "$DF_LBAAS_AUTO_ENABLE_VIP_PORTS"

        if is_service_enabled q-dhcp ; then
            iniset $DRAGONFLOW_CONF df use_centralized_ipv6_DHCP "True"
        else
            iniset $NEUTRON_CONF DEFAULT dhcp_agent_notification "False"
        fi

        if [[ "$DF_RUNNING_IN_GATE" == "True" ]]; then
            iniset $NEUTRON_CONF quotas default_quota "-1"
            iniset $NEUTRON_CONF quotas quota_network "-1"
            iniset $NEUTRON_CONF quotas quota_subnet "-1"
            iniset $NEUTRON_CONF quotas quota_port "-1"
            iniset $NEUTRON_CONF quotas quota_router "-1"
            iniset $NEUTRON_CONF quotas quota_floatingip "-1"
            iniset $NEUTRON_CONF quotas quota_security_group_rule "-1"
        fi

        # load dragonflow.ini into neutron-server
        neutron_server_config_add_new $DRAGONFLOW_CONF
    fi

    iniset $DRAGONFLOW_CONF df remote_db_hosts "$REMOTE_DB_HOSTS"
    iniset $DRAGONFLOW_CONF df nb_db_class "$NB_DRIVER_CLASS"
    iniset $DRAGONFLOW_CONF df enable_neutron_notifier "$ENABLE_NEUTRON_NOTIFIER"
    iniset $DRAGONFLOW_CONF df enable_dpdk "$ENABLE_DPDK"
    iniset $DRAGONFLOW_CONF df management_ip "$HOST_IP"
    iniset $DRAGONFLOW_CONF df local_ip "$TUNNEL_ENDPOINT_IP"
    iniset $DRAGONFLOW_CONF df tunnel_types "$TUNNEL_TYPES"
    iniset $DRAGONFLOW_CONF df integration_bridge "$INTEGRATION_BRIDGE"
    iniset $DRAGONFLOW_CONF df apps_list "$DF_APPS_LIST"
    iniset $DRAGONFLOW_CONF df_l2_app l2_responder "$DF_L2_RESPONDER"
    iniset $DRAGONFLOW_CONF df enable_df_pub_sub "$DF_PUB_SUB"
    iniset $DRAGONFLOW_CONF df_zmq ipc_socket "$DF_ZMQ_IPC_SOCKET"
    if [[ ! -z ${EXTERNAL_HOST_IP} ]]; then
        iniset $DRAGONFLOW_CONF df external_host_ip "$EXTERNAL_HOST_IP"
        iniset $DRAGONFLOW_CONF df_snat_app external_network_bridge "$PUBLIC_BRIDGE"
    fi

    iniset $DRAGONFLOW_CONF df enable_selective_topology_distribution \
                            "$DF_SELECTIVE_TOPO_DIST"
    configure_df_metadata_service

    if is_service_enabled df-skydive ; then
        configure_df_skydive
    fi
}

function install_zeromq {
    if is_fedora; then
        install_package zeromq
    elif is_ubuntu; then
        install_package libzmq3-dev
    elif is_suse; then
        install_package libzmq3-dev
    fi
    # Necessary directory for socket location.
    sudo mkdir -p /var/run/openstack
    sudo chown $STACK_USER /var/run/openstack
}

function install_df {
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
        run_process df-controller "$DF_LOCAL_CONTROLLER_BINARY --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
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

function verify_os_ken_version {
    # Verify os_ken is installed. Version greater than 0.3.0. Does not return
    # on failure.
    OS_KEN_VER_LINE=`osken --version 2>&1 | head -n 1`
    OS_KEN_VER=`echo $OS_KEN_VER_LINE | cut -d' ' -f2`
    echo "Found os_ken version $OS_KEN_VER ($OS_KEN_VER_LINE)"
    if [ `vercmp_numbers "$OS_KEN_VER" "0.3.0"` -lt 0 ]; then
        die $LINENO "os_ken version $OS_KEN_VER too low. Version 0.3.0+ is required for Dragonflow."
    fi
}

function start_pubsub_service {
    if is_service_enabled df-publisher-service ; then
        echo "Starting Dragonflow publisher service"
        run_process df-publisher-service "$DF_PUBLISHER_SERVICE_BINARY --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF --config-file $DRAGONFLOW_PUBLISHER_CONF"
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
        run_process df-metadata "$DF_METADATA_SERVICE --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_df_metadata_agent {
    if is_service_enabled df-metadata ; then
        echo "Stopping Dragonflow metadata service"
        stop_process df-metadata
        pushd $DRAGONFLOW_DIR
        # TODO(snapiri) When we add more switch backends, this should be conditional
        tools/ovs_metadata_service_deployment.sh remove $INTEGRATION_BRIDGE $DF_METADATA_SERVICE_INTERFACE
        popd
    fi
}

function start_df_bgp_service {
    if is_service_enabled df-bgp ; then
        echo "Starting Dragonflow BGP dynamic routing service"
        run_process df-bgp "$DF_BGP_SERVICE --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function start_df_skydive {
    if is_service_enabled df-skydive ; then
        echo "Starting Dragonflow skydive service"
        run_process df-skydive "$DF_SKYDIVE_SERVICE --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_df_skydive {
    if is_service_enabled df-skydive ; then
        echo "Stopping Dragonflow skydive service"
        stop_process df-skydive
    fi
}

function setup_rootwrap_filters {
    if [[ "$DF_INSTALL_DEBUG_ROOTWRAP_CONF" == "True" ]]; then
        echo "Adding rootwrap filters"
        sudo mkdir -p -m 755 $NEUTRON_CONF_DIR/etc/rootwrap.d
        sudo cp -p $DRAGONFLOW_DIR/etc/rootwrap.d/* $NEUTRON_CONF_DIR/etc/rootwrap.d
    fi
}

function stop_df_bgp_service {
    if is_service_enabled df-bgp ; then
       echo "Stopping Dragonflow BGP dynamic routing service"
       stop_process df-bgp
    fi
}

function handle_df_stack_install {
    if [[ "$OFFLINE" != "True" ]]; then
        if ! is_neutron_enabled ; then
            install_neutron
        fi
        install_df
        if [[ "$DF_REINSTALL_OVS" == "True" ]]; then
            install_ovs
        fi
    fi
    setup_develop $DRAGONFLOW_DIR
    if [[ "$DF_REINSTALL_OVS" == "True" ]]; then
        init_ovs
        # We have to start at install time, because Neutron's post-config
        # phase runs ovs-vsctl.
        start_ovs
    fi
    if function_exists nb_db_driver_start_server; then
    nb_db_driver_start_server
    fi
    disable_libvirt_apparmor
}

function handle_df_stack_post_install {
    init_neutron_sample_config
    configure_ovs
    configure_df_plugin
    # configure nb db driver
    if function_exists nb_db_driver_configure; then
        nb_db_driver_configure
    fi
    # initialize the nb db
    init_nb_db

    if [[ "$DF_PUB_SUB" == "True" ]]; then
        # Implemented by the pub/sub plugin
        configure_pubsub_service_plugin
        # Defaults, in case no Pub/Sub service was selected
        if [ -z $PUB_SUB_DRIVER ]; then
            die $LINENO "pub-sub enabled, but no pub-sub driver selected"
        fi
    fi

    if is_service_enabled nova; then
        configure_neutron_nova
    fi

    if is_service_enabled df-publisher-service; then
        start_pubsub_service
    fi

    start_df
    start_df_metadata_agent
    start_df_bgp_service
    setup_rootwrap_filters
    start_df_skydive
    install_package jq
}

function handle_df_stack {
    if [[ "$STAGE" == "install" ]]; then
        handle_df_stack_install
    elif [[ "$STAGE" == "post-config" ]]; then
        handle_df_stack_post_install
    fi
}

function handle_df_unstack {
    stop_df_skydive
    stop_df_bgp_service
    stop_df_metadata_agent
    stop_df
    if function_exists nb_db_driver_clean; then
        nb_db_driver_clean
    fi
    if [[ "$DF_REINSTALL_OVS" == "True" ]]; then
        cleanup_ovs
        stop_ovs
        uninstall_ovs
    fi
    if is_service_enabled df-publisher-service; then
        stop_pubsub_service
    fi
}


# main loop
if [[ "$Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER" == "True" ]]; then

    if is_plugin_enabled octavia; then
        # Only define this function if dragonflow is used
        function octavia_create_network_interface_device {
            INTERFACE=$1
            MGMT_PORT_ID=$2
            MGMT_PORT_MAC=$3
            if [ -z "$INTERFACE" ]; then
                die "octavia_create_network_interface_device for dragonflow: Interface not given (1st parameter)"
            fi
            if [ -z "$MGMT_PORT_ID" ]; then
                die "octavia_create_network_interface_device for dragonflow: Management port ID not given (2nd parameter)"
            fi
            if [ -z "$MGMT_PORT_MAC" ]; then
                die "octavia_create_network_interface_device for dragonflow: Management port MAC not given (3rd parameter)"
            fi
            sudo ovs-vsctl -- --may-exist add-port $INTEGRATION_BRIDGE $INTERFACE -- set Interface $INTERFACE type=internal -- set Interface $INTERFACE external-ids:iface-status=active -- set Interface $INTERFACE external-ids:attached-mac=$MGMT_PORT_MAC -- set Interface $INTERFACE external-ids:iface-id=$MGMT_PORT_ID -- set Interface $INTERFACE external-ids:skip_cleanup=true
        }

        function octavia_delete_network_interface_device {
            : # Do nothing
        }
    fi

    if [[ "$ACTION" == "stack" ]]; then
        handle_df_stack
    elif [[ "$ACTION" == "unstack" ]]; then
        handle_df_unstack
    fi
fi
