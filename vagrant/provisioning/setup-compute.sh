#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/etcd_compute_node.conf ~/devstack/local.conf
if [ "$1" != "" ]; then
    sed -i -e 's/<IP address of host running everything else>/'$1'/g' ~/devstack/local.conf
fi

# Get the IP address
ipaddress=$(/sbin/ifconfig enp0s8 | grep 'inet addr' | awk -F' ' '{print $2}' | awk -F':' '{print $2}')

# Adjust some things in local.conf
sed -i -e 's/<compute_node_management_IP_Address>/'$ipaddress'/g' ~/devstack/local.conf
sed -i -e 's/<compute_node_data_plane_IP_Address>/'$ipaddress'/g' ~/devstack/local.conf
cat << DEVSTACKEOF >> devstack/local.conf

HOSTNAME=$(hostname)
DEVSTACKEOF

~/devstack/stack.sh
