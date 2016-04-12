#!/bin/bash

deleteInvalid=1
filter="ERROR"
if [ $# -eq 0 ]
        then
                echo "No arguments supplied"
                echo "usage:"
                echo "./deleteAllVMs.sh name_of_VM delete_only_ERROR (boolean: 1 means only ERROR. 0 means delete all)"
                exit 1
fi
if [ $# -eq 2 ]
        then
                echo "Going to delete all $1 VMs"
                deleteInvalid=$2
#                               read -p
fi

echo "================================="
echo "Deleting all exiting VMs by name."
echo "================================="

if [ $deleteInvalid == 0 ]; then
        filter="\|"
fi

cnt=0
for V in `nova list | grep $filter | grep $1 | awk '{print $2}' | grep -v ^ID | grep -v ^$`
do
        echo "deleting VM $V";
        nova delete $V;
        cnt=$((cnt + 1))
done

echo "Total deleted VMs: $cnt"
