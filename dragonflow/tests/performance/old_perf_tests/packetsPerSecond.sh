#!/bin/bash

numOfRuns=10

eastWestIPsArr=("10.0.1.6" "10.0.1.4" "10.0.1.5" "192.168.0.5" "192.168.0.3" "192.168.0.4")
northSouthIPsArr=("10.100.200.203" "10.100.200.201" "10.100.200.202")
sNATIPsArr=("10.100.200.11")

# Packets per second tests
for IP in "${eastWestIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Packets per second East-West test on $IP run #: $i"
		sudo bash -c "timeout 10 hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2>>pktPerSec_East-West.txt
        sleep 5
	done
done

for IP in "${northSouthIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Packets per second North-South test on $IP run #: $i"
		sudo bash -c "timeout 10 hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2>>pktPerSec_North-South.txt
        sleep 5
	done
done

for IP in "${sNATIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Packets per second SNAT test on $IP run #: $i"
		sudo bash -c "timeout 10 hping3 $IP -q -i u20 --icmp|tail -n10 >/dev/null" 2>>pktPerSec_SNAT.txt
        sleep 5
	done
done
