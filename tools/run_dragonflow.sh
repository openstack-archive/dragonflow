#!/bin/bash

# First get all the arguments
while test ${#} -gt 0; do
  case $1 in
    --dragonflow_ip)
      shift
      DRAGONFLOW_IP=$1
      ;;
    --db_ip)
      shift
      DB_IP=$1
      ;;
    --management_ip)
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

# SET DRAGONFLOW_IP and DB_IP on the ini file
if [ ! -d /etc/dragonflow ]; then
  mkdir -p /etc/dragonflow
fi
if [ ! -e /etc/dragonflow/dragonflow.ini ]; then
  sed -e "s/LOCAL_IP/$DRAGONFLOW_IP/g" etc/standalone/dragonflow.ini | \
    sed -e "s/MANAGEMENT_IP/$MANAGEMENT_IP/g" | \
    sed -e "s/DB_SERVER_IP/$DB_IP/g"  > /etc/dragonflow/dragonflow.ini
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
elif [ -z "$DF_NO_BASH" ]; then
  /bin/bash
fi
