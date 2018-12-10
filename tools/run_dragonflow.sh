#!/bin/bash

VERB=""
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
    --nb_db_driver)
      shift
      NB_DB_DRIVER=$1
      ;;
    --pubsub_driver)
      shift
      PUBSUB_DRIVER=$1
      ;;
    --)
      shift
      break
      ;;
    *)
      if [ -n "$VERB" ]; then
        echo >&2 "Unknown command line argument: $1"
        exit 1
      fi
      VERB=$1
      shift
      ;;
  esac
  shift
done

# Use defaults if not supplied
NB_DB_DRIVER=${NB_DB_DRIVER:-etcd_nb_db_driver}
PUBSUB_DRIVER=${PUBSUB_DRIVER:-etcd_pubsub_driver}

if [ ! -d /etc/dragonflow ]; then
  mkdir -p /etc/dragonflow
fi
# Set parameters to the ini file
if [ ! -e /etc/dragonflow/dragonflow.ini ]; then
  sed -e "s/LOCAL_IP/$DRAGONFLOW_IP/g" etc/standalone/dragonflow.ini | \
    sed -e "s/MANAGEMENT_IP/$MANAGEMENT_IP/g" | \
    sed -e "s/DB_SERVER_IP/$DB_IP/g" | \
    sed -e "s/NB_DB_DRIVER/$NB_DB_DRIVER/g" | \
    sed -e "s/PUBSUB_DRIVER/$PUBSUB_DRIVER/g"  > /etc/dragonflow/dragonflow.ini
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

case "$VERB" in
  ""|"controller")
    /usr/local/bin/df-local-controller --config-file /etc/dragonflow/dragonflow.ini
    ;;
  "bash")
    /bin/bash
    ;;
  "rest")
    df-model -j -o /var/dragonflow_model.json
    pip install bottle
    /usr/local/bin/df-rest-service --config /etc/dragonflow/dragonflow.ini --host 0.0.0.0 --json /var/dragonflow_model.json
    ;;
  "noop")
    echo "Dragonflow script end"
    ;;
  *)
    echo>&2 "Warning: Unknown option supplied to Dragonflow: $VERB"
    ;;
esac
