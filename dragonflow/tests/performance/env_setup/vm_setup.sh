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

sudo apt-get update
sudo apt-get -y install hping3 iperf netperf

iperf -s -u -i 1 -p 8686&
iperf -s&

# This code allows running the services on the VM after VM reboots
#sudo -s
#echo "#!/bin/sh -e" > /etc/rc.local
#echo "iperf -s -u -i 1 -p 8686&" >> /etc/rc.local
#echo "iperf -s&" >> /etc/rc.local
#echo "exit 0" >> /etc/rc.local
#sudo /etc/rc.local
