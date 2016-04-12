#!/bin/bash

sudo apt-get update
sudo apt-get -y install hping3 iperf

iperf -s -u -i 1 -p 8686&
iperf -s&

sudo -s

echo "#!/bin/sh -e" > /etc/rc.local
echo "iperf -s -u -i 1 -p 8686&" >> /etc/rc.local
echo "iperf -s&" >> /etc/rc.local
echo "exit 0" >> /etc/rc.local
sudo /etc/rc.local
