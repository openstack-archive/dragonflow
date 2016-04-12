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
