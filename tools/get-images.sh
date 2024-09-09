#!/bin/bash
#
# This script returns list of container images that are managed by this charm and/or its workload
#
# dynamic list

set -xe

IMAGE_LIST=()
IMAGE_LIST+=($(find -type f -name metadata.yaml -exec yq '.resources | to_entries | .[] | .value | ."upstream-source"' {} \; | tr -d '"'))
IMAGE_LIST+=($(find -type f -name config.yaml -exec yq '.options | with_entries(select(.key | test("-image$"))) | .[].default' {} \; | tr -d '"'))
printf "%s\n" "${IMAGE_LIST[@]}"
