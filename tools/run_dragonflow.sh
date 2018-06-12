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
    --db_init)
      DB_INIT=1
      ;;
    --)
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
if [ ! -e /etc/dragonflow/dragonflow.ini ]; then
  mkdir -p /etc/dragonflow
  sed -e "s/LOCAL_IP/$DRAGONFLOW_ADDRESS/g" etc/standalone/dragonflow.ini | \
    sed -e "s/DB_SERVER_IP/$DB_ADDRESS/g"  > /etc/dragonflow/dragonflow.ini
fi
if [ -n "$DB_INIT" ]; then
  df-db init
fi

/usr/local/bin/df-local-controller --config-file /etc/dragonflow/dragonflow.ini

