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
controllerNode="$(cat ../configuration.conf | grep controllerNode | tr "=\"" " " | awk '{print $2}')"
computeNode="$(cat ../configuration.conf | grep computeNode | tr "=\"" " " | awk '{print $2}')"
CN_userName="$(cat ../configuration.conf | grep CN_userName | tr "=\"" " " | awk '{print $2}')"
CN_IP="$(cat ../configuration.conf | grep CN_IP | tr "=\"" " " | awk '{print $2}')"
numOfVMs="$(cat ../configuration.conf | grep numOfVMs | tr "=\"" " " | awk '{print $2}')"
l2_subnet="$(cat ../configuration.conf | grep l2_subnet | tr "=\"" " " | awk '{print $2}')"
l3_subnet="$(cat ../configuration.conf | grep l3_subnet | tr "=\"" " " | awk '{print $2}')"
# End configuration

freshInstall=0

if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./setup_environment.sh fresh-setup (1-fresh setup. 0-use exiting environment.) sync-SSH-keys (1-yes, 0-no)"
	exit 1
fi
if [ $# -eq 2 ]; then
	freshInstall=$1
fi

if [ $freshInstall == 1 ]; then
	echo -e "==========\nSetting up a fresh devstack installation\n=========="
	if [ ! -d "~/devstack/" ]; then
		git clone https://git.openstack.org/openstack-dev/devstack
	else
		git pull
	fi
	cd ~/devstack
	./unstack
	sudo rm -r /opt/stack/
	./stack.sh
	. ~/devstack/openrc admin demo
	echo "DF_RUNNING_IN_GATE=True" >> ~/devstack/local.conf
	echo -e "==========\nEnded setting up devstack\n=========="
else
	# OpenStack local login
	. ~/devstack/openrc admin demo
	# Deleting all iPerf VMs
	./delete_VMs.sh iPerf 0
fi

# Download and create the iPerf image
echo -e "==========\nPreparing the iPerf image\n=========="
if [ "$(glance image-list | grep iPerfServer | awk '{print $4}')" == "" ]; then
	echo -e "==========\nDownloading ubuntu image from Ubuntu Cloud Images\n=========="
	wget -O /tmp/iPerfServer.img http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-i386-disk1.img

	echo -e "==========\nUploading the image to glance\n=========="
	glance image-create --name='iPerfServer' --container-format=bare --disk-format=qcow2 < /tmp/iPerfServer.img
else
	echo -e "==========\nThe image is already exists\n=========="
fi

echo -e "==========\nCreating two networks and connects them to router\n=========="
python create_net.py private1 $l2_subnet
python create_net.py private2 $l3_subnet
netId1="$(neutron net-list | grep private1 | awk '{print $2}')"
netId2="$(neutron net-list | grep private2 | awk '{print $2}')"

echo -e "==========\nConfiguring security groups, add ingress rules for ICMP and SSH\n=========="
neutron security-group-delete sg1
neutron security-group-create sg1
neutron security-group-rule-create --protocol icmp --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1
neutron security-group-rule-create --protocol tcp --port-range-min 22 --port-range-max 22 --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1
neutron security-group-rule-create --protocol tcp --port-range-min 5001 --port-range-max 5001 --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1
neutron security-group-rule-create --protocol udp --port-range-min 8686 --port-range-max 8686 --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1
neutron security-group-rule-create --protocol tcp --port-range-min 1 --port-range-max 65535 --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1
neutron security-group-rule-create --protocol udp --port-range-min 1 --port-range-max 65535 --direction ingress --remote-ip-prefix 0.0.0.0/0 sg1

echo -e "==========\nDeleting all floating IPs\n=========="
./delete_all_floatingIPs.sh

if [ $2 == 1 ]; then
	echo -e "==========\nCreating SSH keys & enabling remote command execution on $computeNode CN\n=========="
	./enable_remote_command.sh master $CN_userName $CN_IP
	read -rsp $'Press enter to continue...\n'

	echo -e "==========\nImporting the public ssh key to OpenStack.\n=========="
	nova keypair-add --pub-key ~/.ssh/id_rsa.pub ssh-key
fi

# Add the $controllerNode and $computeNode to Host Aggregates
echo -e "==========\nCreating the Host Aggregates\n=========="
nova aggregate-create $controllerNode $controllerNode
nova aggregate-create $computeNode $computeNode
id="$(nova aggregate-list | grep $controllerNode | awk '{print $2}')"
nova aggregate-add-host $id $controllerNode
id="$(nova aggregate-list | grep $computeNode | awk '{print $2}')"
nova aggregate-add-host $id $computeNode

# Creating the VMs on CNs
j=1
for ((i=1;i<=numOfVMs;i++,j++));
do
	echo -e "==========\nCreating iPerf-client$i VM on $computeNode\n=========="
	nova boot --image iPerfServer --flavor m1.small --nic net-id=$netId1 --availability-zone nova:$computeNode --key-name=ssh-key iPerf-client$i
	VMIP="$(nova list | grep iPerf-client$i | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
	vmPortID="$(neutron port-list | grep $VMIP | awk '{print $2}')"
	neutron port-update $vmPortID --security-group=sg1
	echo -e "==========\nCreating iPerf-server$j VM on $controllerNode\n=========="
	nova boot --image iPerfServer --flavor m1.small --nic net-id=$netId1 --availability-zone nova:$controllerNode --key-name=ssh-key iPerf-server$j
	VMIP="$(nova list | grep iPerf-server$j | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
	vmPortID="$(neutron port-list | grep $VMIP | awk '{print $2}')"
	neutron port-update $vmPortID --security-group=sg1
	let "j++"
	echo -e "==========\nCreating iPerf-server$j VM on $controllerNode\n=========="
	nova boot --image iPerfServer --flavor m1.small --nic net-id=$netId2 --availability-zone nova:$controllerNode --key-name=ssh-key iPerf-server$j
	VMIP="$(nova list | grep iPerf-server$j | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
	vmPortID="$(neutron port-list | grep $VMIP | awk '{print $2}')"
	neutron port-update $vmPortID --security-group=sg1
done
sleep 5
for ((i=1;i<=numOfVMs;i++));
do
	echo -e "==========\nCreating iPerf-server$j VM on $computeNode\n=========="
	nova boot --image iPerfServer --flavor m1.small --nic net-id=$netId1 --availability-zone nova:$computeNode --key-name=ssh-key iPerf-server$j
	VMIP="$(nova list | grep iPerf-server$j| tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
	vmPortID="$(neutron port-list | grep $VMIP | awk '{print $2}')"
	neutron port-update $vmPortID --security-group=sg1
	let "j++"
	echo -e "==========\nCreating iPerf-server$j VM on $computeNode\n=========="
	nova boot --image iPerfServer --flavor m1.small --nic net-id=$netId2 --availability-zone nova:$computeNode --key-name=ssh-key iPerf-server$j
	VMIP="$(nova list | grep iPerf-server$j | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
	vmPortID="$(neutron port-list | grep $VMIP | awk '{print $2}')"
	neutron port-update $vmPortID --security-group=sg1
	let "j++"
done

# Associate Floating-IPs to VMs
VMsList="$(nova list | grep "10.\|192." | tr -s ',' ' ' | tr -s '=' ' ' | awk '{print $13}' | tr "\n" " ")"
# Converting from string to array
VMsList=($VMsList)
for ip in "${VMsList[@]}";
do
        echo -e "==========\nAssociating Floating-IP address to $ip VM\n=========="
        vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
        neutron floatingip-create --port-id $vmPortID public
done
sleep 5
# Preparing VMs for test
for ip in "${VMsList[@]}";
do
	vmPortID="$(neutron port-list | grep $ip | awk '{print $2}')"
	floatingIP="$(neutron floatingip-list | grep $vmPortID | awk '{print $6}')"
	echo -e "==========\nSetting up iPerf and hPing3 on $floatingIP VM\n=========="
	scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no vm_setup.sh ubuntu@$floatingIP:/tmp/
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$floatingIP 'chmod +x /tmp/vm_setup.sh'
	ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no ubuntu@$floatingIP 'sudo /tmp/vm_setup.sh'&
	# It is also possible to do this by accessing the VM through the name-space of the router.
done

echo -e "==========\nStarting iPerf servers on $computeNode CN2\n=========="
ssh $CN_userName@$CN_IP 'sudo apt-get -y install hping3 iperf netperf'
ssh $CN_userName@$CN_IP 'iperf -s -u -i 1 -p 8686&'&
ssh $CN_userName@$CN_IP 'iperf -s&'&
ssh $CN_userName@$CN_IP 'netserver&'&

echo -e "====================\nFinished setting up the test environment.\n===================="
