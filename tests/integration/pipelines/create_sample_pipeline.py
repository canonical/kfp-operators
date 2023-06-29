#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

# Example of a simple pipeline. This scrip will create a pipeline
# object and then compile it into a yaml file.
# Based on: https://www.kubeflow.org/docs/components/pipelines/v2/compile-a-pipeline/

from kfp import dsl
from kfp import compiler

@dsl.component
def comp(message: str) -> str:
    print(message)
    return message

@dsl.pipeline
def my_pipeline(message: str) -> str:
    """My ML pipeline."""
    return comp(message=message).output

compiler.Compiler().compile(my_pipeline, package_path='pipeline.yaml')
