#!/bin/bash

computeName=""

if [ $# -eq 0 ]
	then
		echo "No arguments supplied"
		echo "usage:"
		echo "./create-VMsOn2Nets_byCN.sh number_of_VMs Compute_Name (Compute_Name is optional)"
		exit 1
fi
if [ $# -eq 2 ]
	then
		computeName=$2
fi

numOfVms=$1
cnt=0
sleepTime=1

echo "===================================="
echo "Creating $numOfVms on two networks"
echo "===================================="
for ((i=1; i<=numOfVms; i++)); do
        echo "Creating VM #$i on Private Network 1 on $2"
	if [ ! -z "$computeName" -a "$computeName" != " " ]; then
	   python create-VM.py private1 $2
	else
	   python create-VM.py private1
	fi

        echo "sleeping $sleepTime secs"
        sleep $sleepTime

	i=$((i + 1))
	echo "Creating VM #$i On Private Network 2 $2"
	if [ ! -z "$computeName" -a "$computeName" != " " ]; then
	   python create-VM.py private2 $2
	else
	   python create-VM.py private2
	fi
		
        echo "sleeping $sleepTime secs"
        sleep $sleepTime
		
	cnt=$((cnt + 1))
	if [ $cnt == 60 ]; then
		cnt=0
		echo "========================================"
		echo "sleeping 5 secs, after 60 VMs creation."
		echo "========================================"
		sleep 5
	fi
done
