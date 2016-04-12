#!/bin/bash

# This script enables the ability to remotely execute commands on other Linux machines

masterSlave=""

if [ $# -eq 0 ]; then
	echo "No arguments supplied"
	echo "usage:"
	echo "./enable_remote_command.sh master/slave slaveUser (optional) slaveMachine_IP (optional)"
	echo "Slave is the machine where you want to the run command from the master machine"
	echo "Need to specify the IP and userName of the slave machine while running the script on the master machine"
	exit 1
fi
if [ $# -gt 0 ]; then
	masterSlave=$1
fi

if [ $masterSlave = "master" ]; then
	cd ~/
	ssh-keygen -t rsa
	ssh-add .ssh/id_rsa
	sudo killall -9 ssh-agent
	eval `ssh-agent`
	scp -r .ssh $2@$3:~/
	echo "Done. Now run this script on the slave machine"
elif [ $masterSlave = "slave" ]; then
	cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys
	chmod 600 ~/.ssh/authorized_keys
	echo "Done. Now you can run commands on this machine from the master machine thru SSH."
	echo "e.g. run this from master: ssh slaveUser@slaveIP 'ip add show'"
else
	echo "please check the specified script arguments"
	exit 1
fi
