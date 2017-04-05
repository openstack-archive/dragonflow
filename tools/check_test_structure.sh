#!/usr/bin/env bash

# This script identifies the unit test modules that do not correspond
# directly with a module in the code tree.

dragonflow_path=$(cd "$(dirname "$0")/.." && pwd)
base_unit_test_path=dragonflow/tests/unit
unit_test_path=$dragonflow_path/$base_unit_test_path

unit_test_files=$(find ${unit_test_path} -iname 'test_*.py')

error_count=0
total_count=0
for test_file in ${unit_test_files[@]}; do
    relative_path=${test_file#$unit_test_path/}
    expected_path=$(dirname $dragonflow_path/dragonflow/$relative_path)
    test_filename=$(basename "$test_file")
    expected_filename=${test_filename#test_}
    # Module filename (e.g. foo/bar.py -> foo/test_bar.py)
    filename=$expected_path/$expected_filename
    # Package dir (e.g. foo/ -> test_foo.py)
    package_dir=${filename%.py}
    if [ ! -f "$filename" ] && [ ! -d "$package_dir" ]; then
        echo "Unexpected test file: $base_unit_test_path/$relative_path"
        ((error_count++))
    fi
    ((total_count++))
done

if [ "$error_count" -eq 0 ]; then
    echo 'Success!  All test modules match targets in the code tree.'
    exit 0
else
    echo "Failure! $error_count of $total_count test modules do not match targets in the code tree."
    exit 1
fi
