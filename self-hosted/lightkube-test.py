from lightkube import Client
from lightkube.resources.core_v1 import Node

client = Client()
for node in client.list(Node):
    print("Successfully listed nodes from host using lightkube!")
    print(node.metadata.name)
