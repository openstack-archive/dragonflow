#!/bin/bash

numOfRuns=10

eastWestIPsArr=("10.0.1.6" "10.0.1.4" "10.0.1.5" "192.168.0.5" "192.168.0.3" "192.168.0.4")
northSouthIPsArr=("10.100.200.203" "10.100.200.201" "10.100.200.202")
sNATIPsArr=("10.100.200.11")

# UDP tests
for IP in "${eastWestIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP East-West test on $IP run #: $i"
        iperf -c $IP -u -p 8686 >> datagramLossNJitter_East-West.txt
        sleep 5
        done
done

for IP in "${northSouthIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP North-South test on $IP run #: $i"
        iperf -c $IP -u -p 8686 >> datagramLossNJitter_North-South.txt
        sleep 5
        done
done

for IP in "${sNATIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP SNAT test on $IP run #: $i"
        iperf -c $IP -u -p 8686 >> datagramLossNJitter_SNAT.txt
        sleep 5
        done
done

# UDP 100MB tests - 100MB
for IP in "${eastWestIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP East-West 100MB test on $IP run #: $i"
        iperf -c $IP -u -b 100MB -p 8686 >> datagramLossNJitter100MB_East-West.txt
        sleep 5
        done
done

for IP in "${northSouthIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP North-South 100MB test on $IP run #: $i"
        iperf -c $IP -u -b 100MB -p 8686 >> datagramLossNJitter100MB_North-South.txt
        sleep 5
        done
done

for IP in "${sNATIPsArr[@]}";
do
        for ((i=0; i<numOfRuns; i++)); do
        echo "UDP SNAT 100MB test on $IP run #: $i"
        iperf -c $IP -u -b 100MB -p 8686 >> datagramLossNJitter100MB_SNAT.txt
        sleep 5
        done
done