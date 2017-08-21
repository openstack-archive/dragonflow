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

# Taken from neutron_dynamic_router's gate hook
# NOTE(kakuma)
# Check apparmor to avoid the following error for docker operation.
#   "oci runtime error: apparmor failed to apply profile: no such file or directory"
# This is a temporary solution. This needs to be fixed in a better way.
function check_apparmor_for_docker {
    if [[ -d $APPARMOR_PROFILE_PATH ]]
    then
        if [[ ! -f $APPARMOR_PROFILE_PATH/docker ]]
        then
cat << EOF > /tmp/docker
#include <tunables/global>


profile docker-default flags=(attach_disconnected,mediate_deleted) {

  #include <abstractions/base>


  network,
  capability,
  file,
  umount,

  deny @{PROC}/* w,   # deny write for all files directly in /proc (not in a subdir)
  # deny write to files not in /proc/<number>/** or /proc/sys/**
  deny @{PROC}/{[^1-9],[^1-9][^0-9],[^1-9s][^0-9y][^0-9s],[^1-9][^0-9][^0-9][^0-9]*}/** w,
  deny @{PROC}/sys/[^k]** w,  # deny /proc/sys except /proc/sys/k* (effectively /proc/sys/kernel)
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,  # deny everything except shm* in /proc/sys/kernel/
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/mem rwklx,
  deny @{PROC}/kmem rwklx,
  deny @{PROC}/kcore rwklx,

  deny mount,

  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/fs/cg[^r]*/** wklx,
  deny /sys/firmware/efi/efivars/** rwklx,
  deny /sys/kernel/security/** rwklx,


  # suppress ptrace denials when using 'docker ps' or using 'ps' inside a container
  ptrace (trace,read) peer=docker-default,

}
EOF
            chmod 0644 /tmp/docker
            sudo chown root:root /tmp/docker
            sudo mv /tmp/docker $APPARMOR_PROFILE_PATH/docker
            sudo service apparmor restart
            sudo service docker restart
        fi
    fi
}

if [ "$VENV" == "fullstack" ]; then
    GATE_DEST=$BASE/new
    DEVSTACK_PATH=$GATE_DEST/devstack
elif [ "$VENV" == "tempest" ]; then
    sudo apt-get update
    sudo apt-get install -y --reinstall apparmor
    configure_docker_test_env
    check_apparmor_for_docker
else
    echo >&2 "Unknown gate-hook environment: $VENV"
    exit 1
fi

$BASE/new/devstack-gate/devstack-vm-gate.sh
