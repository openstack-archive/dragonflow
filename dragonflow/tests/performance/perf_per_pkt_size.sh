#!/bin/bash

# Start configuration
testTime=100
# End configuration

. ~/devstack/openrc admin demo
clear

declare -a eastWestIPsArr="$(head -1 conf_file | tail -1 | tr "\n" " ")"
eastWestIPsArr=($eastWestIPsArr)

echo -e "==========\nConfiguring the client-VMs\n=========="
VMsList="$(nova list | grep "iPerf-client" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"
	floatingIPs+=($clientFloatingIP)
done

customTest() {
	echo -e "==========\nRunning the test with packet size: $1 Bytes on all VMs in parallel\n=========="
	index=0
	for clientFloatingIP in "${floatingIPs[@]}";
	do
		#echo -e "==========\nRunning: ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP \"netperf -l "$testTime" -H "${eastWestIPsArr[$index]}" -t TCP_STREAM -- -m "$1"\"\n=========="
		ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "netperf -l "$testTime" -H "${eastWestIPsArr[$index]}" -t TCP_STREAM -- -m "$1 2>/dev/null | grep ^" "[0-9] &
		index=$(($index+1))
	done
}

customTest 2048
echo -e "===================================================================================================\n"
sleep $(($testTime+2))
customTest 1024
echo -e "===================================================================================================\n"
sleep $(($testTime+2))
customTest 512
echo -e "===================================================================================================\n"
sleep $(($testTime+2))
customTest 64
echo -e "===================================================================================================\n"
