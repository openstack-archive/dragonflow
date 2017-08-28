#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/etcd_controller_node.conf ~/devstack/local.conf

# Get the IP address
ipaddress=$(/sbin/ifconfig enp0s8 | grep 'inet addr' | awk -F' ' '{print $2}' | awk -F':' '{print $2}')

# Adjust some things in local.conf
sed -i -e 's/<controller_management_IP_Address>/'$ipaddress'/g' ~/devstack/local.conf
sed -i -e 's/<controller_data_plane_IP_Address>/'$ipaddress'/g' ~/devstack/local.conf
cat << DEVSTACKEOF >> devstack/local.conf

# Adjust this in case we're running on a cloud which may use 10.0.0.x
# for VM IP addresses
NETWORK_GATEWAY=10.100.100.100
FIXED_RANGE=10.100.100.0/24

# Good to set these
HOSTNAME=$(hostname)
SERVICE_HOST_NAME=${HOSTNAME}
SERVICE_HOST=$ipaddress
DEVSTACKEOF

~/devstack/stack.sh
