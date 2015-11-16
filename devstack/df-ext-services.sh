#!/usr/bin/env bash

# Detect path for this script file
DF_DIR=$(cd $(dirname "$0") && pwd)

# Main include for all openstack functions
source openrc

# Include other dragonflow scripts
source $DF_DIR/settings
source $DF_DIR/plugin.sh

# Start ovs db and etcd/ramcloud
start_ovs
