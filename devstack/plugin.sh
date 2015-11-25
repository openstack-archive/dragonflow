# dragonflow.sh - Devstack extras script to install Dragonflow

# The git repo to use
OVS_REPO=${OVS_REPO:-http://github.com/openvswitch/ovs.git}
OVS_REPO_NAME=$(basename ${OVS_REPO} | cut -f1 -d'.')

# The branch to use from $OVS_REPO
OVS_BRANCH=${OVS_BRANCH:-origin/master}

DEFAULT_NB_DRIVER_CLASS="dragonflow.db.drivers.etcd_db_driver.EtcdDbDriver"
DEFAULT_TUNNEL_TYPE="geneve"
DEFAULT_APPS_LIST="l2_app.L2App,l3_app.L3App,dhcp_app.DHCPApp"

# How to connect to ovsdb-server hosting the OVS databases.
REMOTE_DB_IP=${REMOTE_DB_IP:-$HOST_IP}
REMOTE_DB_PORT=${REMOTE_DB_PORT:-4001}
NB_DRIVER_CLASS=${NB_DRIVER_CLASS:-$DEFAULT_NB_DRIVER_CLASS}
TUNNEL_TYPE=${TUNNEL_TYPE:-$DEFAULT_TUNNEL_TYPE}
DF_APPS_LIST=${DF_APPS_LIST:-$DEFAULT_APPS_LIST}

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
        iniset $NEUTRON_CONF df nb_db_class "$NB_DRIVER_CLASS"
        iniset $NEUTRON_CONF df local_ip "$HOST_IP"
        iniset $NEUTRON_CONF df tunnel_type "$TUNNEL_TYPE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
        iniset $NEUTRON_CONF DEFAULT advertise_mtu "True"
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""
    fi

    if ! is_service_enabled q-svc; then
        _create_neutron_conf_dir
        NEUTRON_CONF=/etc/neutron/neutron.conf
        cp $NEUTRON_DIR/etc/neutron.conf $NEUTRON_CONF
        iniset $NEUTRON_CONF df remote_db_ip "$REMOTE_DB_IP"
        iniset $NEUTRON_CONF df remote_db_port $REMOTE_DB_PORT
        iniset $NEUTRON_CONF df nb_db_class "$NB_DRIVER_CLASS"
        iniset $NEUTRON_CONF df local_ip "$HOST_IP"
        iniset $NEUTRON_CONF df tunnel_type "$TUNNEL_TYPE"
        iniset $NEUTRON_CONF df apps_list "$DF_APPS_LIST"
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

function install_df {

    nb_db_driver_install_server

    nb_db_driver_install_client

    echo_summary "Installing DragonFlow"
    git_clone $DRAGONFLOW_REPO $DRAGONFLOW_DIR $DRAGONFLOW_BRANCH

    echo "Cloning and installing Ryu"
    git_clone $RYU_REPO $RYU_DIR $RYU_BRANCH
    pushd $RYU_DIR
    setup_package ./ -e
    popd
    echo "Finished installing Ryu"
}

# install_ovs() - Collect source and prepare
function install_ovs {
    local _pwd=$(pwd)
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

    cd $DEST
    if [ ! -d $OVS_REPO_NAME ] ; then
        git clone $OVS_REPO
        cd $OVS_REPO_NAME
        git checkout $OVS_BRANCH
    else
        cd $OVS_REPO_NAME
    fi

    install_package python-openvswitch

    # TODO: Can you create package list files like you can inside devstack?
    install_package autoconf automake libtool gcc patch make

    if [ ! -f configure ] ; then
        ./boot.sh
    fi
    if [ ! -f config.status ] || [ configure -nt config.status ] ; then
        ./configure --with-linux=/lib/modules/`uname -r`/build
    fi
    make -j$[$(nproc) + 1]
    sudo make install
    sudo make modules_install
    sudo chown $(whoami) $OVS_DIR
    sudo chown $(whoami) /usr/local/var/log/openvswitch

    cd $_pwd
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
        run_process db-ext-services "bash $DEST/dragonflow/devstack/df-ext-services.sh"
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

# main loop
if [[ "$Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        if [[ "$OFFLINE" != "True" ]]; then
            install_df
            install_ovs
        fi
        echo export PYTHONPATH=\$PYTHONPATH:$DRAGONFLOW_DIR:$RYU_DIR >> $RC_DIR/.localrc.auto
        init_ovs
        # We have to start at install time, because Neutron's post-config
        # phase runs ovs-vsctl.
        nb_db_driver_start_server
        start_ovs
        disable_libvirt_apparmor
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        configure_df_plugin

        if is_service_enabled nova; then
            create_nova_conf_neutron
        fi

        start_df
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_df
        cleanup_ovs
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
