#!/bin/bash

. ~/devstack/openrc admin demo

FIPList="$(neutron floatingip-list | awk '{print $2}' | grep -P '(\d)')"
FIPList=($FIPList)
for FIP in "${FIPList[@]}";
do
        echo "Deleting: $FIP"
        neutron floatingip-delete $FIP
done
