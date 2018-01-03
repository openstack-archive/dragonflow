#!/bin/bash

# If no root path was supplied, we assume we are at the root of DragonFlow
# project
DRAGONFLOW_DIR=${1:-.}

SRC_FILE=${DRAGONFLOW_DIR}/dragonflow/controller/common/constants.py
DEST_FILE=${2:-${DRAGONFLOW_DIR}/tools/add_table_names}

# The following one-liner awk script does the magic.
# First - adds the script prefix
# Then - it parses the SRC_FILE, for every constant that contains the word
# TABLE, it creates an entry in the awk file dictionary from the table ID to
# its name
# Lastly - after all lines are done, it adds the hard-coded actual body of
# the script
awk 'BEGIN {FS="="; print "#!/bin/awk -f\n\nBEGIN {"}; /^[^#].*TABLE[\w]*/{gsub(" ", ""); name=$1; id=$2; line="  id_to_name["id"]=\""name"\""; print line }; END {print "}\n\n{\n  head = \"\"\n  tail=$0\n  while (match(tail, /(resubmit\\(,|table=)([0-9]+)/, arr)) {\n    repl = substr(tail, RSTART, RLENGTH)\n    head = head substr(tail,1, RSTART-1) repl \"(\" id_to_name[arr[2]] \")\"\n    tail = substr(tail, RSTART+RLENGTH)\n  }\n  print head tail\n}\n"}' ${SRC_FILE} > ${DEST_FILE}
chmod +x ${DEST_FILE}
