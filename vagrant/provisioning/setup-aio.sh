#!/usr/bin/env bash
cp /dragonflow/doc/source/single-node-conf/etcd_local_controller.conf ~/devstack/local.conf

# Get the IP address
ipaddress=$(ifconfig eth1 2>/dev/null|awk '/inet addr:/ {split($2,a,":"); print a[2]}')

# Adjust some things in local.conf
cat << DEVSTACKEOF >> devstack/local.conf

# Adjust this in case we're running on a cloud which may use 10.0.0.x
# for VM IP addresses
NETWORK_GATEWAY=10.100.100.100
FIXED_RANGE=10.100.100.0/24

HOST_IP=$ipaddress

# Good to set these
HOSTNAME=$(hostname)
SERVICE_HOST_NAME=\${HOSTNAME}
SERVICE_HOST=$ipaddress

USE_PYTHON3=True
DEVSTACKEOF

~/devstack/stack.sh
