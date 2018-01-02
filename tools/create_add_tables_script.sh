#!/bin/bash

# If no root path was supplied, we assume we are at the root of dragonflow project
DRAGONFLOW_DIR=${1:-.}

DEST_FILE=${2:-${DRAGONFLOW_DIR}/tools/add_table_names}

awk 'BEGIN {FS="="; print "#!/bin/awk -f\n\nBEGIN {"}; /^[^#].*TABLE[\w]*/{ name=gensub(" ", "", "g", $1); id=gensub(" ", "", "g", $2); line="  id_to_name["id"]=\""name"\""; print line }; END {print "}\n\n{\n  head = \"\"\n  tail=$0\n  while (match(tail, /(resubmit\\(,|table=)([0-9]+)/, arr)) {\n    repl = substr(tail, RSTART, RLENGTH)\n    head = head substr(tail,1,RSTART-1) repl \"(\" id_to_name[arr[2]] \")\"\n    tail = substr(tail,RSTART+RLENGTH)\n  }\n  print head tail\n}\n"}' ${DRAGONFLOW_DIR}/dragonflow/controller/common/constants.py > ${DEST_FILE}
chmod +x ${DEST_FILE}
