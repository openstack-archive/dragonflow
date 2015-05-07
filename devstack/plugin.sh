# dragonflow.sh - Devstack extras script to install Dragonflow

if [[ "$Q_ENABLE_DRAGONFLOW" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "DragonFlow pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing DragonFlow"

        git_clone $DRAGONFLOW_REPO $DRAGONFLOW_DIR $DRAGONFLOW_BRANCH

        if is_service_enabled q-df-l3; then
           echo "Cloning and installing Ryu"
           git_clone $RYU_REPO $RYU_DIR $RYU_BRANCH
           sed -i 's/register_cli_opts/register_opts/g' $RYU_DIR/ryu/controller/controller.py
           sed -i 's/register_cli_opts/register_opts/g' $RYU_DIR/ryu/controller/controller.py
           setup_develop $RYU_DIR
           echo "Finished installing Ryu"
        fi

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configure DragonFlow"

        if is_service_enabled q-df-l3; then
           _configure_neutron_l3_agent
        fi

        iniset $NEUTRON_CONF DEFAULT L3controller_ip_list $Q_DF_CONTROLLER_IP
        iniset /$Q_PLUGIN_CONF_FILE agent enable_l3_controller "True"
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
