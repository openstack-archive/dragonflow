#!/bin/bash

numOfRuns=10

eastWestIPsArr=("10.0.1.6" "10.0.1.4" "10.0.1.5" "192.168.0.5" "192.168.0.3" "192.168.0.4")
northSouthIPsArr=("10.100.200.203" "10.100.200.201" "10.100.200.202")
sNATIPsArr=("10.100.200.11")

# Bandwidth tests
for IP in "${eastWestIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Bandwidth East-West test on $IP run #: $i"
        iperf -c $IP >> bandwidth_East-West.txt
        sleep 5
	done
done

for IP in "${northSouthIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Bandwidth North-South test on $IP run #: $i"
        iperf -c $IP >> bandwidth_North-South.txt
        sleep 5
	done
done

for IP in "${sNATIPsArr[@]}";
do
	for ((i=0; i<numOfRuns; i++)); do
        echo "Bandwidth SNAT test on $IP run #: $i"
        iperf -c $IP >> bandwidth_SNAT.txt
        sleep 5
	done
done
