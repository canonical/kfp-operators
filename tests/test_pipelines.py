from kfp import Client, dsl
from subprocess import check_output
import json


def gcs_download_op(url):
    return dsl.ContainerOp(
        name="GCS - Download",
        image="google/cloud-sdk:279.0.0",
        command=["sh", "-c"],
        arguments=["gsutil cat $0 | tee $1", url, "/tmp/results.txt"],
        file_outputs={
            "data": "/tmp/results.txt",
        },
    )


def echo2_op(text1, text2):
    return dsl.ContainerOp(
        name="echo",
        image="library/bash:4.4.23",
        command=["sh", "-c"],
        arguments=['echo "Text 1: $0"; echo "Text 2: $1"', text1, text2],
    )


@dsl.pipeline(
    name="Parallel pipeline",
    description="Download two messages in parallel and prints the concatenated result.",
)
def download_and_join(
    url1="gs://ml-pipeline/sample-data/shakespeare/shakespeare1.txt",
    url2="gs://ml-pipeline/sample-data/shakespeare/shakespeare2.txt",
):
    """A three-step pipeline with first two running in parallel."""

    download1_task = gcs_download_op(url1)
    download2_task = gcs_download_op(url2)

    echo2_op(download1_task.output, download2_task.output)


def test_pipelines():
    status = json.loads(
        check_output(
            [
                "microk8s",
                "kubectl",
                "get",
                "services/kfp-api",
                "-nkubeflow",
                "-ojson",
            ]
        ).decode("utf-8")
    )
    ip = status["spec"]["clusterIP"]
    client = Client(f"http://{ip}:8888")
    run = client.create_run_from_pipeline_func(
        download_and_join,
        arguments={
            "url1": "gs://ml-pipeline/sample-data/shakespeare/shakespeare1.txt",
            "url2": "gs://ml-pipeline/sample-data/shakespeare/shakespeare2.txt",
        },
    )
    completed = client.wait_for_run_completion(run.run_id, timeout=3600)
    status = completed.to_dict()["run"]["status"]
    assert status == "Succeeded", f"Pipeline cowsay status is {status}"
