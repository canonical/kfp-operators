#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# DEBUGGING KFP integration tests: comment to trigger pull request workflow
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
printf "%s\n" "${IMAGE_LIST[@]}"
