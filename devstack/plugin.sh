# dragonflow.sh - Devstack extras script to install Dragonflow

if is_service_enabled q-df-svc; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
	
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
        iniset $NEUTRON_CONF DEFAULT service_plugins $DF_L3_SERVICE_PLUGIN
        iniset $NEUTRON_CONF DEFAULT L3controller_ip_list $Q_DF_CONTROLLER_IP
        iniset /$Q_PLUGIN_CONF_FILE agent enable_l3_controller "True"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing DragonFlow"
    
        if is_service_enabled q-df-agt; then 
             run_process q-df-agt "python $DF_L2_AGENT --config-file $NEUTRON_CONF --config-file /$Q_PLUGIN_CONF_FILE"
        fi

        if is_service_enabled q-df-l3; then
    	     run_process q-df-l3 "python $DF_L3_AGENT"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then
        if is_service_enabled q-df-agt; then 
           stop_process q-df-agt
        fi

        if is_service_enabled q-df-l3; then
           stop_process q-df-l3
        fi
    fi
fi
