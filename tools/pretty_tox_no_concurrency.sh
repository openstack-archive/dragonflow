#! /bin/sh

TESTRARGS=$1

exec 3>&1
status=$(exec 4>&1 >&3; ( python setup.py testr --slowest --testr-args="--concurrency=1 --subunit $TESTRARGS"; echo $? >&4 ) | $(dirname $0)/subunit-trace.py -f) && exit $status
