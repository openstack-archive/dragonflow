#!/bin/bash

# TBD - Need to take this info from the existing OpenStack environment and a from the config file
numOfRuns=10

eastWestIPsArr=(
	"10.1.0.9"
	"10.1.0.10"
	"10.1.0.11"
	"10.1.0.13"
	"192.168.0.6"
	"192.168.0.7"
	"192.168.0.8"
	"192.168.0.9"
)

VM2FIPIPsArr=(
	"10.100.200.202"
	"10.100.200.203"
	"10.100.200.204"
	"10.100.200.205"
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
			iperf -c $IP | tee -a $2.txt $IP.txt
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
			iperf -c $IP -u -p 8686 | tee -a $2.txt $IP.txt
			sleep 5
		done
	done
}

# UDP tests - DatagramLoss and Jitter - 30MB
udp30MB() {
	declare -a ipsArr=("${!1}")
	for IP in "${ipsArr[@]}";
	do
		for ((i=0; i<numOfRuns; i++)); do
			echo "$2 30MB test on $IP run #: $i"
			iperf -c $IP -u -b 30MB -p 8686 | tee -a $2_30MB.txt $IP.txt
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
			ping -c 10 -i 0.2 -w 3 $IP | tee -a $2.txt $IP.txt
			sleep 1
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
			sudo bash -c "timeout 10 hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2 | tee -a $2.txt $IP.txt
			sleep 5
		done
	done
}

echo "Starting Bandwidth tests"
bandwidth eastWestIPsArr[@] bandwidth_eastWest
bandwidth VM2FIPIPsArr[@] bandwidth_VM2FIP
bandwidth sNATIPsArr[@] bandwidth_SNAT
echo "Finished Bandwidth tests. Sleep 5."
sleep 5

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
