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
CN_IP="$(cat configuration.conf | grep CN_IP | tr "=\"" " " | awk '{print $2}')"

l2_subnet="$(cat configuration.conf | grep l2_subnet | tr "=\"" " " | awk '{print $2}')"
l3_subnet="$(cat configuration.conf | grep l3_subnet | tr "=\"" " " | awk '{print $2}')"
numOfVMs="$(cat configuration.conf | grep numOfVMs | tr "=\"" " " | awk '{print $2}')"
testTime="$(cat configuration.conf | grep testTime | tr "=\"" " " | awk '{print $2}')"
# End configuration

eastWestIPsArr=()
VM2FIPIPsArr=()
sNATIPsArr=()
sNATIPsArr+=($CN_IP)
floatingIPs=()

# OpenStack local login
. ~/devstack/openrc admin demo

clear
echo -e "==========\nParsing OpenStack VMs IP addresses and generating the test configuration file\n=========="
VMsList="$(nova list | grep "iPerf-server" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | sort -V | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	eastWestIPsArr+=($ip)
	# Only for 192.X subnet adding to array its FIP
	vmPortID="$(neutron port-list | grep $ip | grep "192." | awk '{print $2}')"
	if [ ! -z $vmPortID ]; then
		floatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"
		VM2FIPIPsArr+=($floatingIP)
	fi
done
echo ${eastWestIPsArr[@]} > conf_file
echo ${VM2FIPIPsArr[@]} >> conf_file
echo ${sNATIPsArr[@]} >> conf_file

echo "l2_subnet=$l2_subnet" >> conf_file
echo "l3_subnet=$l3_subnet" >> conf_file
echo "numOfVMs=$numOfVMs" >> conf_file
echo "testTime=$testTime" >> conf_file

# This code will allow executing the Bandwidth tests from the VMs
#echo -e "==========\nConfiguring the client-VMs\n=========="
#VMsList="$(nova list | grep "iPerf-client" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
#VMsList=($VMsList)
#for ip in "${VMsList[@]}";
#do
#	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
#	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"
#	floatingIPs+=($clientFloatingIP)

#	echo -e "==========\nUploading files to the iPerf-client - $clientFloatingIP VM\n=========="
#	scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no run_perf_tests.sh ubuntu@$clientFloatingIP:/tmp/
#	scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no conf_file ubuntu@$clientFloatingIP:/tmp/
#	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP 'chmod +x /tmp/run_perf_tests.sh'
#done

# This sleep allows running the clients in parallel
#sleep 1
#echo -e "==========\nRunning bandwidth tests on all VMs in parallel\n=========="
#for clientFloatingIP in "${floatingIPs[@]}";
#do	
#	echo -e "==========\nStarting the bandwidth tests from - $clientFloatingIP VM\n=========="
	# Each VM sending traffic to other VM, the numOfVMs parameter is used as an array index, which holds the servers list
#	numOfVMs=$(($numOfVMs-1))
#	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "sudo /tmp/run_perf_tests.sh 1 "$numOfVMs&
#done
#echo -e "==========\nSleeping $(($testTime*5)) seconds - waiting to test completion\n=========="
#sleep $(($testTime*5))

dirname="$(date +"%d-%m-%y_"%H-%M"")"
mkdir $dirname

./perf_per_pkt_size.sh $dirname

echo -e "==========\nConfiguring the client-VM\n=========="
clientVM="$(nova list | grep "iPerf-client1" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
vmPortID="$(neutron port-list | grep $clientVM | awk '{print $2}')"
clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"

echo -e "==========\nUploading files to the iPerf-client - $clientFloatingIP\n=========="
scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no run_perf_tests.sh ubuntu@$clientFloatingIP:/tmp/
scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no conf_file ubuntu@$clientFloatingIP:/tmp/
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP 'chmod +x /tmp/run_perf_tests.sh'

echo -e "==========\nStarting the rest of the tests from a single client - $clientFloatingIP VM\n=========="
ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP 'sudo /tmp/run_perf_tests.sh 0'

echo -e "==========\nDownloading the tests results from - $clientFloatingIP to folder: $dirname\n=========="
scp -r -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP:/tmp/*.txt ./$dirname

rm conf_file
# This code will allow copy the Bandwidth tests results from the VMs
#for clientFloatingIP in "${floatingIPs[@]}";
#do
#	scp -r -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP:/tmp/*.txt ./$dirname
#done

# Creating the test report
./results_parser.sh $dirname
cp -r report-template $dirname
cp $dirname/testResults.txt $dirname/report-template
mv $dirname/report-template $dirname/report
echo -e "========================================\n"
echo "Link to the test report: $dirname/report/report/data_plane_report.html"
echo -e "========================================\n"
