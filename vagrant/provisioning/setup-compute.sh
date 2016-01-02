#!/usr/bin/env bash
cp /dragonflow/doc/source/multi-node-conf/compute_node_local_controller.conf ~/devstack/local.conf
if [ "$1" != "" ]; then
    sed -i -e 's/<IP address of host running everything else>/'$1'/g' ~/devstack/local.conf
fi
~/devstack/stack.sh
