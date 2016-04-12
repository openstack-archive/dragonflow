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
	   python create-VM.py test private1 $2
	else
	   python create-VM.py test private1
	fi

	echo "sleeping $sleepTime secs"
	sleep $sleepTime

	i=$((i + 1))
	echo "Creating VM #$i On Private Network 2 $2"
	if [ ! -z "$computeName" -a "$computeName" != " " ]; then
	   python create-VM.py test private2 $2
	else
	   python create-VM.py test private2
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
