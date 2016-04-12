#!/bin/bash

# Start configuration
testTime=50
# End configuration

if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./run_perf_tests.sh onlyBandwidth (1-on Bandwidth. 0-All tests.) bandwidthIndex (1-N: used only with onlyBandwidth set to 1)"
	exit 1
fi

numOfRuns=1
ipIndex=$2

cd /tmp

declare -a eastWestIPsArr="$(head -1 conf_file | tail -1 | tr "\n" " ")"
declare -a VM2FIPIPsArr="$(head -2 conf_file | tail -1 | tr "\n" " ")"
declare -a sNATIPsArr="$(head -3 conf_file | tail -1 | tr "\n" " ")"

# Bandwidth tests
bandwidth() {
	IPsArr=(${!1})
	localIP="$(ifconfig | grep Bcast | tr -s ':' ' ' | awk '{print $3}')"
	if [ $2 == "bandwidth_SNAT" ]; then
		# In SNAT scenario, all IPs pointing to single IP
		ipIndex=0
	fi
	IP=${IPsArr[$ipIndex]}
	for ((i=0; i<numOfRuns; i++)); do
		echo "$2 test on $IP run #: $i"
		iperf -c $IP -t $testTime -P 30 | tee -a $2_$localIP.txt
		sleep 5
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
	for IP in $(echo ${!1});
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			iperf -c $IP -u -p 8686 -t $testTime | tee -a $2.txt $IP.txt
			sleep 5
		done
	done
}

# UDP tests - DatagramLoss and Jitter - 30MB
udp30MB() {
	for IP in $(echo ${!1});
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 30MB test on $IP run #: $i"
			iperf -c $IP -u -b 30MB -p 8686 -t $testTime | tee -a $2_30MB.txt $IP.txt
			sleep 5
		done
	done
}

# Latency tests
latency() {
	for IP in $(echo ${!1});
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			ping -c $testTime -i 0.2 -w 3 $IP | tee -a $2.txt $IP.txt
			sleep 1
		done
	done
}

# Packets per second tests
packetsPerSecond() {
	for IP in $(echo ${!1});
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			sudo bash -c "timeout $testTime hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2>> $2.txt
			sleep 5
		done
		cat $2.txt | tee -a $IP.txt
	done
}

if [ $1 -eq 1 ]; then
	echo "Removing all previous test results"
	sudo rm *.txt
	echo "Starting Bandwidth tests"
	bandwidth eastWestIPsArr[@] bandwidth_eastWest
	bandwidth VM2FIPIPsArr[@] bandwidth_VM2FIP
	bandwidth sNATIPsArr[@] bandwidth_SNAT
	echo "Finished Bandwidth tests. Sleep 5."
elif [ $1 -eq 0 ]; then
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
