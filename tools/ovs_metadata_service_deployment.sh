#!/bin/bash

ACTION=$1; shift
INTEGRATION_BRIDGE=${1:-"br-int"}; shift
DF_METADATA_SERVICE_INTERFACE=${1:-"tap-metadata"}; shift

function usage {
    cat>&2<<EOF
        USAGE: $0 <action> [<integration-bridge>] [<interface>] [<IP>]
        action - install / remove
        integration-bridge - name of the integration bridge (br-int)
        interface - name of the interface to add to the bridge (tap-metadata)
        IP - address to assign to the interface (169.254.169.254)
EOF
}

if [ -z "$ACTION" ]; then
    usage
    exit 1
fi

case $ACTION in
    install)
        DF_METADATA_SERVICE_IP=$i{1:-"169.254.169.254"}; shift

        sudo ovs-vsctl add-port $INTEGRATION_BRIDGE $DF_METADATA_SERVICE_INTERFACE -- set Interface $DF_METADATA_SERVICE_INTERFACE type=internal
        sudo ip addr add dev $DF_METADATA_SERVICE_INTERFACE $DF_METADATA_SERVICE_IP/0
        sudo ip link set dev $DF_METADATA_SERVICE_INTERFACE up
        sudo ip route add 0.0.0.0/0 dev $DF_METADATA_SERVICE_INTERFACE table 2
        sudo ip rule add from $DF_METADATA_SERVICE_IP table 2
	;;
    remove)
        sudo ovs-vsctl del-port $INTEGRATION_BRIDGE $DF_METADATA_SERVICE_INTERFACE
	;;
    *)
	usage
	exit 1
	;;
esac

