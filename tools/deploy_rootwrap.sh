#!/usr/bin/env bash

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -eu

if [ "$#" -ne 2 ]; then
    >&2 echo "Usage: $0 /path/to/dragonflow /path/to/target/etc
Deploy dragonflow's rootwrap configuration."
    exit 1
fi

dragonflow_path=$1
dst_conf_path=$2

src_rootwrap_path=${dragonflow_path}/etc/rootwrap.d
dst_rootwrap_path=${dst_conf_path}/rootwrap.d

if [ ! -d ${dst_rootwrap_path} ]; then
  mkdir -p -m 755 ${dst_rootwrap_path}
fi
cp -p ${src_rootwrap_path}/* ${dst_rootwrap_path}/
