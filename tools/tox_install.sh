#!/bin/sh

# Many of neutron's repos suffer from the problem of depending on neutron,
# but it not existing on pypi.

# This wrapper for tox's package installer will use the existing package
# if it exists, else use zuul-cloner if that program exists, else grab it
# from neutron master via a hard-coded URL. That last case should only
# happen with devs running unit tests locally.

# From the tox.ini config page:
# install_command=ARGV
# default:
# pip install {opts} {packages}

ZUUL_CLONER=/usr/zuul-env/bin/zuul-cloner
neutron_installed=$(echo "import neutron" | python 2>/dev/null ; echo $?)
BRANCH_NAME=master

set -ex

cwd=$(/bin/pwd)

CONSTRAINTS_FILE=$1
shift

install_cmd="pip install"
if [ $CONSTRAINTS_FILE != "unconstrained" ]; then
    install_cmd="$install_cmd -c$CONSTRAINTS_FILE"
fi

if [ $neutron_installed -eq 0 ]; then
    echo "ALREADY INSTALLED" > /tmp/tox_install.txt
    echo "Neutron already installed; using existing package"
elif [ -x "$ZUUL_CLONER" ]; then
    echo "ZUUL CLONER" > /tmp/tox_install.txt
    cd /tmp
    export ZUUL_BRANCH=${ZUUL_BRANCH-$BRANCH}
    $ZUUL_CLONER --cache-dir \
        /opt/git \
        --branch $BRANCH_NAME \
        git://git.openstack.org \
        openstack/neutron
    cd openstack/neutron
    $install_cmd -e .
    cd "$cwd"
else
    echo "PIP HARDCODE" > /tmp/tox_install.txt
    $install_cmd -U -egit+https://git.openstack.org/openstack/neutron@$BRANCH_NAME#egg=neutron
fi

$install_cmd -U $*
exit $?
