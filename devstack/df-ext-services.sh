#!/bin/bash

# Detect path for this script file
DF_DIR=$(cd $(dirname "$0") && pwd)

# Main include for all openstack functions
source openrc

# Include other dragonflow scripts
source $DF_DIR/settings
source $DF_DIR/plugin.sh

# Stop etcd/ramcloud used by dragonflow
nb_db_driver_stop_server
# Stop ovs db
killall ovsdb-server 2&> /dev/null

if [ -e /usr/local/var/run/openvswitch/ovsdb-server.pid ]
then
  OVSDB_PID=$(cat /usr/local/var/run/openvswitch/ovsdb-server.pid 2>/dev/null)
  if [ -e /proc/$OVSDB_PID ]
  then
    # ovsdb process is alive
    sleep 1
    killall ovsdb-server 2&> /dev/null
  fi
fi

# Start ovs db and etcd/ramcloud
start_ovs
