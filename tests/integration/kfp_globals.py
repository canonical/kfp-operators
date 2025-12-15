#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Global variables for functional tests."""
from pathlib import Path

import yaml

basedir = Path("./").absolute()
CHARM_PATH_TEMPLATE = "{basedir}/charms/{charm}/"
# All charms in the kfp-operators repository, except kfp-profile-controller
KFP_CHARMS = [
    "kfp-api",
    "kfp-metadata-writer",
    "kfp-persistence",
    "kfp-profile-controller",
    "kfp-schedwf",
    "kfp-ui",
    "kfp-viewer",
    "kfp-viz",
]

# Variables for uploading/creating pipelines/experiments/runs
SAMPLE_PIPELINES_PATH = f"{basedir}/tests/integration/pipelines"
SAMPLE_PIPELINE = f"{SAMPLE_PIPELINES_PATH}/pipeline_container_no_input.yaml"

SAMPLE_PIPELINE_NAME = "sample-pipeline"

# Variables for creating a viewer
SAMPLE_VIEWER = f"{basedir}/tests/integration/viewer/mnist.yaml"
KUBEFLOW_PROFILE_NAMESPACE = "kubeflow-user-example-com"

# Variables for configuring the KFP Client
# It is assumed that the ml-pipeline-ui (kfp-ui) service is port-forwarded
KUBEFLOW_LOCAL_HOST = "http://localhost:8080"
KUBEFLOW_PROFILE_NAMESPACE = "kubeflow-user-example-com"
PROFILE_FILE_PATH = f"{basedir}/tests/integration/profile/profile.yaml"
PROFILE_FILE = yaml.safe_load(Path(PROFILE_FILE_PATH).read_text())
KUBEFLOW_USER_NAME = PROFILE_FILE["spec"]["owner"]["name"]
