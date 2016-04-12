#!/bin/bash

echo -e "==========\nRunning $1 on all clients\n=========="
. ~/devstack/openrc admin demo
VMsList="$(nova list | grep "iPerf" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"

	echo -e "==========\nRunning $1 on - $clientFloatingIP VM\n=========="
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "$1"&
done
