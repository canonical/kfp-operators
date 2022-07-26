# # Copyright 2021 Canonical Ltd.
# # See LICENSE file for licensing details.
#
# NOTE: Disabled because tests need to be refactored for multi-user pipeline authentication

# from kfp import Client, dsl
# from subprocess import check_output
# import json
#
#
# def gcs_download_op(url):
#     return dsl.ContainerOp(
#         name="GCS - Download",
#         image="google/cloud-sdk:279.0.0",
#         command=["sh", "-c"],
#         arguments=["gsutil cat $0 | tee $1", url, "/tmp/results.txt"],
#         file_outputs={
#             "data": "/tmp/results.txt",
#         },
#     )
#
#
# def echo2_op(text1, text2):
#     return dsl.ContainerOp(
#         name="echo",
#         image="library/bash:4.4.23",
#         command=["sh", "-c"],
#         arguments=['echo "Text 1: $0"; echo "Text 2: $1"', text1, text2],
#     )
#
#
# @dsl.pipeline(
#     name="Parallel pipeline",
#     description="Download two messages in parallel and prints the concatenated result.",
# )
# def download_and_join(
#     url1="gs://ml-pipeline/sample-data/shakespeare/shakespeare1.txt",
#     url2="gs://ml-pipeline/sample-data/shakespeare/shakespeare2.txt",
# ):
#     """A three-step pipeline with first two running in parallel."""
#
#     download1_task = gcs_download_op(url1)
#     download2_task = gcs_download_op(url2)
#
#     echo2_op(download1_task.output, download2_task.output)
#
#
# def test_pipelines():
#     # TODO: This does not work atm because of multi-user and authentication.  We need to pass an
#     #       identity into the Client that kfp will accept, and then access namespaced objects
#     #       during out creation/usage of pipelines.
#     #       This should be doable, but not sure how.  Might be able to take what we do in the
#     #       PodDefault applied to our notebook servers?  Or maybe use the bundle-kubeflow
#     #       authorization workflow?
#     status = json.loads(
#         check_output(
#             [
#                 "microk8s",
#                 "kubectl",
#                 "get",
#                 "services/ml-pipeline",
#                 "-nkubeflow",
#                 "-ojson",
#             ]
#         ).decode("utf-8")
#     )
#     ip = status["spec"]["clusterIP"]
#     client = Client(f"http://{ip}:8888")
#     run = client.create_run_from_pipeline_func(
#         download_and_join,
#         arguments={
#             "url1": "gs://ml-pipeline/sample-data/shakespeare/shakespeare1.txt",
#             "url2": "gs://ml-pipeline/sample-data/shakespeare/shakespeare2.txt",
#         },
#         namespace="admin",  # TODO: Use whatever account we add for our CI.
#         service_account="default-editor"
#     )
#     completed = client.wait_for_run_completion(run.run_id, timeout=3600)
#     status = completed.to_dict()["run"]["status"]
#     assert status == "Succeeded", f"Pipeline cowsay status is {status}"
#
