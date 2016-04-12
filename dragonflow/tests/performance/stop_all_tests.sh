#!/bin/bash

echo -e "==========\nStopping all tests on all clients\n=========="
VMsList="$(nova list | grep "iPerf-client" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"

	echo -e "==========\nStopping the test on - $clientFloatingIP VM\n=========="
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP 'sudo killall -9 iperf'&
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP 'sudo killall -9 hping3'&
done
