# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""A v2 pipeline that passes an artifact between steps.

Producing and consuming an artifact forces the KFP launcher to upload the
output artifact to the object store and download it again for the consumer.
This exercises the object-store (MinIO/S3) data path end to end, which is
useful as a functional guard for changes to the object-storage configuration.
"""
from kfp import compiler, dsl
from kfp.dsl import Dataset, Input, Output


@dsl.component(base_image="python:3.9")
def write_data(output_data: Output[Dataset]):
    """Write a message to an output artifact (uploaded to the object store)."""
    message = "hello from the producer"
    with open(output_data.path, "w") as f:
        f.write(message)


@dsl.component(base_image="python:3.9")
def read_data(input_data: Input[Dataset]):
    """Read the message from an input artifact (downloaded from the object store)."""
    with open(input_data.path, "r") as f:
        content = f.read()
    print(f"Read content from artifact: {content}")
    assert content == "hello from the producer", f"Unexpected artifact content: {content}"


@dsl.pipeline(name="v2-data-passing")
def pipeline_data_passing():
    write_task = write_data()
    read_data(input_data=write_task.outputs["output_data"])


if __name__ == "__main__":
    # execute only if run as a script
    compiler.Compiler().compile(
        pipeline_func=pipeline_data_passing, package_path="pipeline_data_passing.yaml"
    )
