#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/etcd_compute_node.conf ~/devstack/local.conf

# Get the IP address
ipaddress=$(ifconfig eth1 2>/dev/null|awk '/inet addr:/ {split($2,a,":"); print a[2]}')

SED_SCRIPT="s/^\(HOST_IP\)=.*/\1=$ipaddress/g"
SED_SCRIPT="$SED_SCRIPT;/TUNNEL_ENDPOINT_IP/d"
SED_SCRIPT="$SED_SCRIPT;s/^\(SERVICE_HOST\)=.*/\1=$1/g"
SED_SCRIPT="$SED_SCRIPT;s/zmq_pubsub_driver/etcd_pubsub_driver/g"

sed -i -e "$SED_SCRIPT" devstack/local.conf

# Adjust some things in local.conf
cat << DEVSTACKEOF >> devstack/local.conf

# Set this to the address of the main DevStack host running the rest of the
# OpenStack services.
HOSTNAME=$(hostname)
DEVSTACKEOF

# Patch to enable IPv6
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo echo "net.ipv6.conf.all.disable_ipv6 = 0" >> /etc/sysctl.conf

~/devstack/stack.sh
