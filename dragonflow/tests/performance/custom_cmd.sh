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

echo -e "==========\nRunning $1 on all clients\n=========="
. ~/devstack/openrc admin demo
VMsList="$(nova list | grep "iPerf" | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	clientFloatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"

	echo -e "==========\nRunning $1 on - $clientFloatingIP VM\n=========="
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$clientFloatingIP "$1"&
done
