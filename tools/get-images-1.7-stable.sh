#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# static list
STATIC_IMAGE_LIST=(
)
# dynamic list
git checkout origin/track/1.7
IMAGE_LIST=()
IMAGE_LIST+=($(find -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))

printf "%s\n" "${STATIC_IMAGE_LIST[@]}"
printf "%s\n" "${IMAGE_LIST[@]}"
