from time import sleep

import lightkube
from lightkube import codecs
from lightkube.resources.core_v1 import Pod


def apply_pod(client, pod_yaml_file):
    with open(pod_yaml_file, 'r') as f:
        for obj in codecs.load_all_yaml(f):
            client.create(obj)


def main():
    client = lightkube.Client()
    pod_name = 'lightkube-pod'
    pod_yaml_file = 'self-hosted/pod.yaml'

    # Apply the Pod YAML
    apply_pod(client, pod_yaml_file)

    # Watch the Pod until it completes
    print("Waiting for pod to suceed...")
    for event in client.watch(Pod, namespace='default'):
        pod = event[1]

        if not pod.status.phase:
            print("Pod has no status, waiting...")
            continue

        if pod.status.phase == "Pending":
            print("Pod is in Pending state, waiting...")
            continue

        if pod.status.phase == "Running":
            print("Pod is in Running state, waiting...")
            continue

        if pod.status.phase == "Failed":
            print("Pod failed!")
            break

        if pod.status.phase == "Succeeded":
            print("Pod succeeded!")
            break


if __name__ == "__main__":
    main()
