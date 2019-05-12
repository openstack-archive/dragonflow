#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/etcd_controller_node.conf ~/devstack/local.conf

# Get the IP address
ipaddress=$(ifconfig eth1 2>/dev/null|awk '/inet addr:/ {split($2,a,":"); print a[2]}')

SED_SCRIPT="s/^\(HOST_IP\)=.*/\1=$ipaddress/g"
SED_SCRIPT="$SED_SCRIPT;/TUNNEL_ENDPOINT_IP/d"

sed -i -e "$SED_SCRIPT" devstack/local.conf

# Adjust some things in local.conf
cat << DEVSTACKEOF >> devstack/local.conf

# Adjust this in case we're running on a cloud which may use 10.0.0.x
# for VM IP addresses
NETWORK_GATEWAY=10.100.100.100
FIXED_RANGE=10.100.100.0/24

# Good to set these
HOSTNAME=$(hostname)
SERVICE_HOST_NAME=${HOSTNAME}
SERVICE_HOST=$ipaddress

USE_PYTHON3=True
DEVSTACKEOF

~/devstack/stack.sh
