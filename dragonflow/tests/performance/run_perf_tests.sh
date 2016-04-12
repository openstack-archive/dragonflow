#!/bin/bash

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#    Developed by Shlomo Narkolayev | shlominar@gmail.com

cd /tmp

# Start configuration
l2_subnet="$(cat conf_file | grep l2_subnet | tr "=\"" " " | awk '{print $2}')"
l3_subnet="$(cat conf_file | grep l3_subnet | tr "=\"" " " | awk '{print $2}')"
numOfVMs="$(cat conf_file | grep numOfVMs | tr "=\"" " " | awk '{print $2}')"
testTime="$(cat conf_file | grep testTime | tr "=\"" " " | awk '{print $2}')"
# End configuration

if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./run_perf_tests.sh onlyBandwidth (1-on Bandwidth. 0-All tests.) bandwidthIndex (1-N: used only with onlyBandwidth set to 1)"
	exit 1
fi

numOfRuns=1
ipIndex=$2

declare -a eastWestIPsArr="$(head -1 conf_file | tail -1 | tr "\n" " ")"
declare -a VM2FIPIPsArr="$(head -2 conf_file | tail -1 | tr "\n" " ")"
declare -a sNATIPsArr="$(head -3 conf_file | tail -1 | tr "\n" " ")"

# Bandwidth tests
bandwidth() {
	IPsArr=(${!1})
	if [ $2 == "bandwidth_SNAT" ]; then
		# In SNAT scenario, all IPs pointing to single IP
		ipIndex=0
	fi
	for ((j=$ipIndex; j<${#IPsArr[@]}; j+=$numOfVMs)); do
		localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
		targetIP=${IPsArr[$j]}
		if [[ $targetIP == $(echo $l2_subnet | tr "." " " | awk '{print $1"."$2"."}')* ]]; then
			if [ "$j" -lt "$numOfVMs" ]; then
				filename=$2-"L2-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L2-crossNode-"$localIP-$targetIP.txt
			fi
		else
			if [ "$j" -lt "$(echo $numOfVMs*3|bc)" ]; then
				filename=$2-"L3-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L3-crossNode-"$localIP-$targetIP.txt
			fi
		fi
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $targetIP run #: $i"
			iperf -c $targetIP -t $testTime -P 30 | tee -a $filename | grep SUM
			sleep 5
		done
	done
}

bandwidthLoop() {
	for IP in $(echo ${!1});
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			iperf -c $IP -t $testTime -P 30 | tee -a $2.txt $IP.txt
			sleep 5
		done
	done
}

# UDP tests - DatagramLoss and Jitter
udp() {
	IPsArr=(${!1})
	for ((j=0; j<${#IPsArr[@]}; j+=$numOfVMs)); do
		localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
		targetIP=${IPsArr[$j]}
		if [[ $targetIP == $(echo $l2_subnet | tr "." " " | awk '{print $1"."$2"."}')* ]]; then
			if [ "$j" -lt "$numOfVMs" ]; then
				filename=$2-"L2-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L2-crossNode-"$localIP-$targetIP.txt
			fi
		else
			if [ "$j" -lt "$(echo $numOfVMs*3|bc)" ]; then
				filename=$2-"L3-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L3-crossNode-"$localIP-$targetIP.txt
			fi
		fi
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $targetIP run #: $i"
			iperf -c $targetIP -u -p 8686 -t $testTime | tee -a $filename
			sleep 5
		done
	done
}

# UDP tests - DatagramLoss and Jitter - 30MB
udp30MB() {
	IPsArr=(${!1})
	for ((j=0; j<${#IPsArr[@]}; j+=$numOfVMs)); do
		localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
		targetIP=${IPsArr[$j]}
		if [[ $targetIP == $(echo $l2_subnet | tr "." " " | awk '{print $1"."$2"."}')* ]]; then
			if [ "$j" -lt "$numOfVMs" ]; then
				filename=$2-"L2-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L2-crossNode-"$localIP-$targetIP.txt
			fi
		else
			if [ "$j" -lt "$(echo $numOfVMs*3|bc)" ]; then
				filename=$2-"L3-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L3-crossNode-"$localIP-$targetIP.txt
			fi
		fi
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 30MB test on $IP run #: $i"
			iperf -c $targetIP -u -b 30MB -p 8686 -t $testTime | tee -a $filename
			sleep 5
		done
	done
}

# Latency tests
latency() {
	IPsArr=(${!1})
	for ((j=0; j<${#IPsArr[@]}; j+=$numOfVMs)); do
		localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
		targetIP=${IPsArr[$j]}
		if [[ $targetIP == $(echo $l2_subnet | tr "." " " | awk '{print $1"."$2"."}')* ]]; then
			if [ "$j" -lt "$numOfVMs" ]; then
				filename=$2-"L2-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L2-crossNode-"$localIP-$targetIP.txt
			fi
		else
			if [ "$j" -lt "$(echo $numOfVMs*3|bc)" ]; then
				filename=$2-"L3-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L3-crossNode-"$localIP-$targetIP.txt
			fi
		fi
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			ping -c $testTime -i 0.2 -w 3 $targetIP | tee -a $filename
			sleep 1
		done
	done
}

# Packets per second tests
packetsPerSecond() {
	IPsArr=(${!1})
	for ((j=0; j<${#IPsArr[@]}; j+=$numOfVMs)); do
		localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
		targetIP=${IPsArr[$j]}
		if [[ $targetIP == $(echo $l2_subnet | tr "." " " | awk '{print $1"."$2"."}')* ]]; then
			if [ "$j" -lt "$numOfVMs" ]; then
				filename=$2-"L2-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L2-crossNode-"$localIP-$targetIP.txt
			fi
		else
			if [ "$j" -lt "$(echo $numOfVMs*3|bc)" ]; then
				filename=$2-"L3-sameNode-"$localIP-$targetIP.txt
			else
				filename=$2-"L3-crossNode-"$localIP-$targetIP.txt
			fi
		fi
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			sudo bash -c "timeout $testTime hping3 $targetIP -q -i u20 --icmp|tail -n10 >/dev/null" 2>> $2.txt
			sleep 5
		done
		cat $2.txt | tee -a $filename.txt
		sudo rm $2.txt
	done
}

# the input allows running specific test from remote
if [ $1 -eq 0 ]; then
	echo "Removing all previous test results"
	sudo rm *.txt
	echo "Starting UDP (Jitter & Datagram loss) tests"
	udp eastWestIPsArr[@] udp_eastWest
	udp VM2FIPIPsArr[@] udp_VM2FIP
	udp sNATIPsArr[@] udp_SNAT
	echo "Finished UDP tests. Sleep 5."
	sleep 5

	echo "Starting UDP (Jitter & Datagram loss) 30MB tests"
	udp30MB eastWestIPsArr[@] udp_eastWest
	udp30MB VM2FIPIPsArr[@] udp_VM2FIP
	udp30MB sNATIPsArr[@] udp_SNAT
	echo "Finished UDP 30MB tests. Sleep 5."
	sleep 5

	echo "Starting Latency tests"
	latency eastWestIPsArr[@] latency_eastWest
	latency VM2FIPIPsArr[@] latency_VM2FIP
	latency sNATIPsArr[@] latency_SNAT
	echo "Finished Latency tests. Sleep 5."
	sleep 5

	echo "Starting PKT/Sec tests"
	packetsPerSecond eastWestIPsArr[@] packetsPerSecond_eastWest
	packetsPerSecond VM2FIPIPsArr[@] packetsPerSecond_VM2FIP
	packetsPerSecond sNATIPsArr[@] packetsPerSecond_SNAT
	echo "Finished PKT/Sec tests."
else
	echo "Error: Wrong input argument."
fi
