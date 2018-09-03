#!/bin/bash

# First get all the arguments
while test ${#} -gt 0; do
  case $1 in
    --dragonflow_address)
      shift
      DRAGONFLOW_ADDRESS=$1
      ;;
    --db_address)
      shift
      DB_ADDRESS=$1
      ;;
    --mgmt_address)
      shift
      MANAGEMENT_IP=$1
      ;;
    --db_init)
      DB_INIT=1
      ;;
    --)
      shift
      break
      ;;
    *)
      echo >&2 "Unknown command line argument: $1"
      exit 1
      ;;
  esac
  shift
done

# SET DRAGONFLOW_ADDRESS and DB_ADDRESS on the ini file
if [ ! -d /etc/dragonflow ]; then
  mkdir -p /etc/dragonflow
fi
if [ ! -e /etc/dragonflow/dragonflow.ini ]; then
  sed -e "s/LOCAL_IP/$DRAGONFLOW_ADDRESS/g" etc/standalone/dragonflow.ini | \
    sed -e "s/MANAGEMENT_IP/$MANAGEMENT_IP/g" | \
    sed -e "s/DB_SERVER_IP/$DB_ADDRESS/g"  > /etc/dragonflow/dragonflow.ini
fi
if [ ! -e /etc/dragonflow/dragonflow_datapath_layout.yaml ]; then
  cp etc/dragonflow_datapath_layout.yaml /etc/dragonflow
fi

if [ ! -e /etc/neutron ]; then
  ln -s /etc/dragonflow /etc/neutron
fi

if [ ! -e /etc/neutron/neutron.conf ]; then
  touch /etc/neutron/neutron.conf
fi

if [ -n "$DB_INIT" ]; then
  df-db init
fi

if [ -z "$DF_NO_CONTROLLER" ]; then
  /usr/local/bin/df-local-controller --config-file /etc/dragonflow/dragonflow.ini
else
  /bin/bash
fi
