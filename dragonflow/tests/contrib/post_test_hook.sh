#!/usr/bin/env bash

set -xe

DRAGONFLOW_DIR="$BASE/new/dragonflow"
TEMPEST_DIR="$BASE/new/tempest"
SCRIPTS_DIR="/usr/os-testr-env/bin/"

venv=${1:-"fullstack"}

function generate_test_logs {
    local path="$1"
    # Compress all $path/*.txt files and move the directories holding those
    # files to /opt/stack/logs. Files with .log suffix have their
    # suffix changed to .txt (so browsers will know to open the compressed
    # files and not download them).
    if [[ -d "$path" ]] ; then
        sudo find "$path" -iname "*.log" -type f -exec mv {} {}.txt \; -exec gzip -9 {}.txt \;
        sudo mv "$path/*" /opt/stack/logs/
    fi
}

function generate_testr_results {
    # Give job user rights to access tox logs
    sudo -H -u "$owner" chmod o+rw .
    sudo -H -u "$owner" chmod o+rw -R .testrepository
    if [[ -f ".testrepository/0" ]] ; then
        ".tox/$venv/bin/subunit-1to2" < .testrepository/0 > ./testrepository.subunit
        $SCRIPTS_DIR/subunit2html ./testrepository.subunit testr_results.html
        gzip -9 ./testrepository.subunit
        gzip -9 ./testr_results.html
        sudo mv ./*.gz /opt/stack/logs/
    fi

    if [[ "$venv" == fullstack* ]] ; then
        generate_test_logs "/tmp/${venv}-logs"
    fi
}

owner=stack
sudo_env=

# virtuelenv 14.0.6 gives a strange error which appears solved in version 15.
# Therefore, we force the newer version.
sudo pip uninstall -y virtualenv
sudo pip install --upgrade "virtualenv>=15.0.1"

# Set owner permissions according to job's requirements.
cd "$DRAGONFLOW_DIR"
sudo chown -R $owner:stack "$DRAGONFLOW_DIR"

# Run tests
echo "Running Dragonflow $venv tests"
set +e
sudo -H -u "$owner" tox -e "$venv"
testr_exit_code=$?
set -e

# Collect and parse results
generate_testr_results
exit $testr_exit_code
