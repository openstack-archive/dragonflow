#!/bin/bash

# start_df_controller - Start Dragonflow local controller
function start_dragonflow_local_controller {
    if is_service_enabled df-controller ; then
        echo "Starting Dragonflow local controller"
        sudo ovs-vsctl --no-wait set-controller $INTEGRATION_BRIDGE tcp:127.0.0.1:6633
        run_process df-controller "$DF_LOCAL_CONTROLLER_BINARY --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_dragonflow_local_controller {
    if is_service_enabled df-controller ; then
        echo "Stopping Dragonflow local controller"
        stop_process df-controller
    fi
}

function get_proc_name_dragonflow_local_controller {
    if is_service_enabled df-controller ; then
        echo df-controller
    fi
}

DRAGONFLOW_ALL_SERVICES+=" local_controller"

function start_dragonflow_pubsub_service {
    if is_service_enabled df-publisher-service ; then
        echo "Starting Dragonflow publisher service"
        run_process df-publisher-service "$DF_PUBLISHER_SERVICE_BINARY --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_dragonflow_pubsub_service {
    if is_service_enabled df-publisher-service ; then
        echo "Stopping Dragonflow publisher service"
        stop_process df-publisher-service
    fi
}

function get_proc_name_dragonflow_pubsub_service {
    if is_service_enabled df-publisher-service ; then
        echo df-pubsub_service
    fi
}

DRAGONFLOW_ALL_SERVICES+=" pubsub_service"

function start_dragonflow_metadata_service {
    if is_service_enabled df-metadata ; then
        echo "Starting Dragonflow metadata service"
        run_process df-metadata "$DF_METADATA_SERVICE --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_dragonflow_metadata_service {
    if is_service_enabled df-metadata ; then
        echo "Stopping Dragonflow metadata service"
        stop_process df-metadata
    fi
}

function get_proc_name_dragonflow_pubsub_service {
    if is_service_enabled df-metadata ; then
        echo df-pubsub_service
    fi
}

DRAGONFLOW_ALL_SERVICES+=" metadata_service"

function start_dragonflow_bgp_service {
    if is_service_enabled df-bgp ; then
        echo "Starting Dragonflow BGP dynamic routing service"
        run_process df-bgp "$DF_BGP_SERVICE --config-file $NEUTRON_CONF --config-file $DRAGONFLOW_CONF"
    fi
}

function stop_dragonflow_bgp_service {
    if is_service_enabled df-bgp ; then
       echo "Stopping Dragonflow BGP dynamic routing service"
       stop_process df-bgp
    fi
}

function get_proc_name_dragonflow_bgp_service {
    if is_service_enabled df-bgp ; then
       echo df-bgp
    fi
}

DRAGONFLOW_ALL_SERVICES+=" bgp_service"

function dragonflow_service {
    SERVICE=$1
    ACTION=$2
    FUNC="${ACTION}_dragonflow_${SERVICE}"
    if ! function_exists $FUNC; then
        die "Cannot $ACTION service $SERVICE: Don't know how"
    fi
    $FUNC
}

function start_dragonflow_services {
    for service in $DRAGONFLOW_ALL_SERVICES; do
        dragonflow_service $service start
    done
}

function stop_dragonflow_services {
    for service in $DRAGONFLOW_ALL_SERVICES; do
        dragonflow_service $service stop
    done
}

function ensure_dragonflow_services {
    set --
    for service in $DRAGONFLOW_ALL_SERVICES; do
        set -- $@ $(dragonflow_service $service get_proc_name)
    done
    ensure_services_started $@
}
