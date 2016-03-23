#!/usr/bin/env bash

# Locate devstack directory
TOP_DIR=

# Detect path for this script file
DF_DIR=$(cd $(dirname "$0") && pwd)

# Main include for all openstack functions
source $TOP_DIR/openrc

# Include other dragonflow scripts
source $DF_DIR/settings
source $DF_DIR/plugin.sh

if ! nb_db_driver_status_server; then
    # make sure the db is stopped
    nb_db_driver_stop_server
    echo "Going to start db"
    nb_db_driver_start_server
fi
