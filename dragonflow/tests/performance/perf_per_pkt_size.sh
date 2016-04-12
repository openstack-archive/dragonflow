#!/bin/bash

# Start configuration
testTime=100
# End configuration

dirname=$1

if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./perf_per_pkt_size.sh directory_name"
	exit 1
fi

. ~/devstack/openrc admin demo
clear

declare -a eastWest="$(head -1 conf_file | tail -1 | tr "\n" " ")"
declare -a VM2FIP="$(head -2 conf_file | tail -1 | tr "\n" " ")"
declare -a sNAT="$(head -3 conf_file | tail -1 | tr "\n" " ")"

echo -e "==========\nConfiguring the client-VMs\n=========="
VMsList="$(nova list | grep "iPerf-client" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"
	floatingIPs+=($clientFloatingIP)
done

bandwidth_test() {
	IPsArr=(${!2})
	echo -e "==========\nRunning the $2 test with packet size: $1 Bytes\n==========\n"
	index=0
	for clientFloatingIP in "${floatingIPs[@]}";
	do
		ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "netperf -l "$testTime" -H "${IPsArr[$index]}" -t TCP_STREAM -- -m "$1 2>/dev/null | grep ^" "[0-9] | tee -a $dirname/bandwidth-$1-$2.txt &
		if [ $2 != "sNAT" ]; then #SNAT scenario is when all clients sending traffic to single destination
			index=$(($index+1))
		fi
	done
	sleep $(($testTime+2))
}

eastWest_bandwidth_test() {
	IPsArr=(${!2})
	echo -e "==========\nRunning the $2 test with packet size: $1 Bytes\n==========\n"
	index=0
	filename=""
	for ((i=0;i<4;i++)); do
		if [ "$i" -eq 0 ]; then
			echo -e "==========\nL2 Cross-Node\n=========="
			filename="L2-CrossNode"
		elif [ "$i" -eq 1 ]; then
			echo -e "==========\nL2 Same-Node\n=========="
			filename="L2-SameNode"
		elif [ "$i" -eq 2 ]; then
			echo -e "==========\nL3 Cross-Node\n=========="
			filename="L3-CrossNode"
		elif [ "$i" -eq 3 ]; then
			echo -e "==========\nL3 Same-Node\n=========="
			filename="L3-SameNode"
		fi
		for clientFloatingIP in "${floatingIPs[@]}";
		do
		#	echo -e "==========\nRunning: ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP \"netperf -l "$testTime" -H "${IPsArr[$index]}" -t TCP_STREAM -- -m "$1"\"\n=========="
			ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "netperf -l "$testTime" -H "${IPsArr[$index]}" -t TCP_STREAM -- -m "$1 2>/dev/null | grep ^" "[0-9] | tee -a $dirname/bandwidth-$1-$2-$filename.txt &
			index=$(($index+1))
		done
		sleep $(($testTime+2))
	done
}

eastWest_bandwidth_test 2048 eastWest
echo -e "===================================================================================================\n"
eastWest_bandwidth_test 1024 eastWest
echo -e "===================================================================================================\n"
eastWest_bandwidth_test 512 eastWest
echo -e "===================================================================================================\n"
eastWest_bandwidth_test 64 eastWest
echo -e "===================================================================================================\n"
bandwidth_test 2048 VM2FIP
echo -e "===================================================================================================\n"
bandwidth_test 1024 VM2FIP
echo -e "===================================================================================================\n"
bandwidth_test 512 VM2FIP
echo -e "===================================================================================================\n"
bandwidth_test 64 VM2FIP
echo -e "===================================================================================================\n"
bandwidth_test 2048 sNAT
echo -e "===================================================================================================\n"
bandwidth_test 1024 sNAT
echo -e "===================================================================================================\n"
bandwidth_test 512 sNAT
echo -e "===================================================================================================\n"
bandwidth_test 64 sNAT
