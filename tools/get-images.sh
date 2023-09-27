#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# dynamic list
IMAGE_LIST=()
IMAGE_LIST+=($(find -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \;))
IMAGE_LIST+=($(find -type f -name config.yaml -exec yq '.options.cache-image |  select(.) | .default' {} \;))
printf "%s\n" "${IMAGE_LIST[@]}"
