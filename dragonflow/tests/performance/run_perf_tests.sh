#!/bin/bash

# TBD - Need to take this info from a config file
numOfRuns=10

eastWestIPsArr=(
	"10.0.1.6"
	"10.0.1.4"
	"10.0.1.5"
	"192.168.0.5"
	"192.168.0.3"
	"192.168.0.4"
)

northSouthIPsArr=(
	"10.100.200.203"
	"10.100.200.201"
	"10.100.200.202"
)

sNATIPsArr=(
	"10.100.200.11"
)

# Bandwidth tests
bandwidth() {
	declare -a ipsArr=("${!1}")
	for IP in "${ipsArr[@]}";
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			iperf -c $IP >> $2.txt
			sleep 5
		done
	done
}

# UDP tests - DatagramLoss and Jitter
udp() {
	declare -a ipsArr=("${!1}")
	for IP in "${ipsArr[@]}";
	do
			for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			iperf -c $IP -u -p 8686 >> $2.txt
			sleep 5
			done
	done
}

# Latency tests
latency() {
	declare -a ipsArr=("${!1}")
	for IP in "${ipsArr[@]}";
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			ping -c 10 -i 0.2 -w 3 $IP >> $2.txt
			sleep 5
		done
	done
}

# Packets per second tests
packetsPerSecond() {
	declare -a ipsArr=("${!1}")
	for IP in "${ipsArr[@]}";
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 test on $IP run #: $i"
			sudo bash -c "timeout 10 hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2>>$2.txt
			sleep 5
		done
	done
}

echo "Starting Bandwidth tests"
bandwidth eastWestIPsArr[@] bandwidth_eastWest
bandwidth northSouthIPsArr[@] bandwidth_northSouth
bandwidth sNATIPsArr[@] bandwidth_SNAT
echo "Finished Bandwidth tests. Sleep 5."
sleep 5

echo "Starting UDP tests"
udp eastWestIPsArr[@] udp_eastWest
udp northSouthIPsArr[@] udp_northSouth
udp sNATIPsArr[@] udp_SNAT
echo "Finished UDP tests. Sleep 5."
sleep 5

echo "Starting Latency tests"
latency eastWestIPsArr[@] latency_eastWest
latency northSouthIPsArr[@] latency_northSouth
latency sNATIPsArr[@] latency_SNAT
echo "Finished Latency tests. Sleep 5."
sleep 5

echo "Starting PKT/Sec tests"
packetsPerSecond eastWestIPsArr[@] packetsPerSecond_eastWest
packetsPerSecond northSouthIPsArr[@] packetsPerSecond_northSouth
packetsPerSecond sNATIPsArr[@] packetsPerSecond_SNAT
echo "Finished PKT/Sec tests."
