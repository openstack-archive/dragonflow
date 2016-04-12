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

# Start configuration
numOfVMs="$(cat configuration.conf | grep numOfVMs | tr "=\"" " " | awk '{print $2}')"
# End configuration

clear
if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./results_parser.sh directory_name"
	exit 1
fi
cd $1

bandwidth_results() {
	pktSum=0
	bdSum=0
	for f in bandwidth-$1-$2*$3*;
	do
		bandwidthValues="$(cat $f | awk '{print $5}')"
		bandwidthValues=($bandwidthValues)
		for v in "${bandwidthValues[@]}";
		do
			bdSum=$(echo print $v + $bdSum | python)
		done
		echo "bandwidth, scenario: $2, packet size: $1, network: $3, bandwidth: $bdSum"
		echo "bandwidth,$2,$1,$3,$bdSum" >> testResults.txt
	done
}

all_but_bandwidth() {
	packetsPerSecond_l2_cross="$(cat packetsPerSecond_eastWest-L2-crossNode* | grep packets | awk '{print $4}')"
	packetsPerSecond_l2_same="$(cat packetsPerSecond_eastWest-L2-sameNode* | grep packets | awk '{print $4}')"
	packetsPerSecond_l3_cross="$(cat packetsPerSecond_eastWest-L3-crossNode* | grep packets | awk '{print $4}')"
	packetsPerSecond_l3_same="$(cat packetsPerSecond_eastWest-L3-sameNode* | grep packets | awk '{print $4}')"
	packetsPerSecond_snat="$(cat packetsPerSecond_SNAT-L3-sameNode* | grep packets | awk '{print $4}')"
	packetsPerSecond_vm2fip="$(cat packetsPerSecond_VM2FIP-L3-sameNode* | grep packets | awk '{print $4}' | tr "\n" " " | awk '{print $1}')"
	
	latency_l2_cross="$(cat latency_eastWest-L2-crossNode* | grep rtt | tr "/" " " | awk '{print $8}')"
	latency_l2_same="$(cat latency_eastWest-L2-sameNode* | grep rtt | tr "/" " " | awk '{print $8}')"
	latency_l3_cross="$(cat latency_eastWest-L3-crossNode* | grep rtt | tr "/" " " | awk '{print $8}')"
	latency_l3_same="$(cat latency_eastWest-L3-sameNode* | grep rtt | tr "/" " " | awk '{print $8}')"
	latency_snat="$(cat latency_SNAT-L3-sameNode* | grep rtt | tr "/" " " | awk '{print $8}')"
	latency_vm2fip="$(cat latency_VM2FIP-L3-sameNode* | grep rtt | tr "/" " " | awk '{print $8}' | tr "\n" " " | awk '{print $1}')"

	udp_l2_cross="$(cat udp_eastWest-L2-crossNode* | grep % | awk '{print $9}' | tr "\n" " " | awk '{print $1}')"
	udp_l2_same="$(cat udp_eastWest-L2-sameNode* | grep % | awk '{print $10}' | tr "\n" " " | awk '{print $1}')"
	udp_l3_cross="$(cat udp_eastWest-L3-crossNode* | grep % | awk '{print $10}' | tr "\n" " " | awk '{print $1}')"
	udp_l3_same="$(cat udp_eastWest-L3-sameNode* | grep % | awk '{print $10}' | tr "\n" " " | awk '{print $1}')"
	udp_snat="$(cat udp_SNAT-L3-sameNode* | grep % | awk '{print $10}' | tr "\n" " " | awk '{print $1}')"
	udp_vm2fip="$(cat udp_VM2FIP-L3-sameNode* | grep % | awk '{print $10}' | tr "\n" " " | awk '{print $1}')"
	
	echo "packetsPerSecond,eastWest,L2,CrossNode,$packetsPerSecond_l2_cross" | tee -a testResults.txt
	echo "packetsPerSecond,eastWest,L2,SameNode,$packetsPerSecond_l2_same" | tee -a testResults.txt
	echo "packetsPerSecond,eastWest,L3,CrossNode,$packetsPerSecond_l3_cross" | tee -a testResults.txt
	echo "packetsPerSecond,eastWest,L3,SameNode,$packetsPerSecond_l3_same" | tee -a testResults.txt
	echo "packetsPerSecond,sNAT,L3,CrossNode,$packetsPerSecond_snat" | tee -a testResults.txt
	echo "packetsPerSecond,VM2FIP,L3,CrossNode,$packetsPerSecond_vm2fip" | tee -a testResults.txt
	
	echo "latency,eastWest,L2,CrossNode,$latency_l2_cross" | tee -a testResults.txt
	echo "latency,eastWest,L2,SameNode,$latency_l2_same" | tee -a testResults.txt
	echo "latency,eastWest,L3,CrossNode,$latency_l3_cross" | tee -a testResults.txt
	echo "latency,eastWest,L3,SameNode,$latency_l3_same" | tee -a testResults.txt
	echo "latency,sNAT,L3,CrossNode,$latency_snat" | tee -a testResults.txt
	echo "latency,VM2FIP,L3,CrossNode,$latency_vm2fip" | tee -a testResults.txt
	
	echo "jitter,eastWest,L2,CrossNode,$udp_l2_cross" | tee -a testResults.txt
	echo "jitter,eastWest,L2,SameNode,$udp_l2_same" | tee -a testResults.txt
	echo "jitter,eastWest,L3,CrossNode,$udp_l3_cross" | tee -a testResults.txt
	echo "jitter,eastWest,L3,SameNode,$udp_l3_same" | tee -a testResults.txt
	echo "jitter,sNAT,L3,CrossNode,$udp_snat" | tee -a testResults.txt
	echo "jitter,VM2FIP,L3,CrossNode,$udp_vm2fip" | tee -a testResults.txt
}

echo "datetime,$(echo $1 | tr -d "/")" > testResults.txt

echo -e "Bandwidth test results\r"
echo -e "========================================\n"
bandwidth_results 2048 eastWest L2-CrossNode
bandwidth_results 2048 eastWest L2-SameNode
bandwidth_results 2048 eastWest L3-CrossNode
bandwidth_results 2048 eastWest L3-SameNode
bandwidth_results 2048 VM2FIP
bandwidth_results 2048 sNAT
echo -e "========================================\n"

bandwidth_results 1024 eastWest L2-CrossNode
bandwidth_results 1024 eastWest L2-SameNode
bandwidth_results 1024 eastWest L3-CrossNode
bandwidth_results 1024 eastWest L3-SameNode
bandwidth_results 1024 VM2FIP
bandwidth_results 1024 sNAT
echo -e "========================================\n"

bandwidth_results 512 eastWest L2-CrossNode
bandwidth_results 512 eastWest L2-SameNode
bandwidth_results 512 eastWest L3-CrossNode
bandwidth_results 512 eastWest L3-SameNode
bandwidth_results 512 VM2FIP
bandwidth_results 512 sNAT
echo -e "========================================\n"

bandwidth_results 64 eastWest L2-CrossNode
bandwidth_results 64 eastWest L2-SameNode
bandwidth_results 64 eastWest L3-CrossNode
bandwidth_results 64 eastWest L3-SameNode
bandwidth_results 64 VM2FIP
bandwidth_results 64 sNAT
echo -e "========================================\n"

echo -e "Latency, Packets/sec and Jitter test results\r"
echo -e "========================================\n"
all_but_bandwidth
echo -e "========================================\n"