#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/compute_node_local_controller.conf ~/devstack/local.conf
if [ "$1" != "" ]; then
    sed -i -e 's/<IP address of host running everything else>/'$1'/g' ~/devstack/local.conf
fi

# Get the IP address
ipaddress=$(/sbin/ifconfig eth1 | grep 'inet addr' | awk -F' ' '{print $2}' | awk -F':' '{print $2}')

# Adjust some things in local.conf
cat << DEVSTACKEOF >> devstack/local.conf

# Set this to the address of the main DevStack host running the rest of the
# OpenStack services.
Q_HOST=$1
HOST_IP=$ipaddress
HOSTNAME=$(hostname)
DEVSTACKEOF

~/devstack/stack.sh
