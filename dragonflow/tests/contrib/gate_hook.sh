#!/usr/bin/env bash

set -ex

VENV=${1:-"fullstack"}

# Taken from neutron_dynamic_router's gate hook
function configure_docker_test_env {
    local docker_pkg

    sudo bash -c 'echo "tempest ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers'
    if apt-cache search docker-engine | grep docker-engine; then
        docker_pkg=docker-engine
    else
        docker_pkg=docker.io
    fi
    sudo apt-get install -y $docker_pkg
    sudo service docker restart
}

if [ "$VENV" == "fullstack" ]; then
    GATE_DEST=$BASE/new
    DEVSTACK_PATH=$GATE_DEST/devstack
elif [ "$VENV" == "tempest" ]; then
    configure_docker_test_env
else
    echo >&2 "Unknown gate-hook environment: $VENV"
    exit 1
fi

$BASE/new/devstack-gate/devstack-vm-gate.sh
