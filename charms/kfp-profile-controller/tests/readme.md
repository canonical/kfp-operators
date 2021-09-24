# Manual Testing

To manually test this charm, you can:

* deploy metacontroller charm
* deploy kubeflow-profiles charm (the regular one)
* deploy minio
* deploy kfp-profile-controller & relate to minio

Juju should now make a kfp-profile-controller pod/service, a metacontroller `CompositeController` object.  Once they're up, any namespace associated with a Profile (from the kubeflow-profile charm) should have a few easily distinguished pods/services etc added to them (named things like 'kfp-visualization').

For a deeper look behind the scenes as it works:

* `kubectl logs` on metacontroller's pod (the real pod, not the juju operator's pod) and it gives a nice log of the namespaces it is checking
* `kubectl logs` on the kfp-profile-controller that deploys the sync.py webserver. Whenever it gets hit with a valid request it'll print the json that it returns
