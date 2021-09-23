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

You can also directly test the actual controller in the kfp-profile-controller charm by doing the following from an existing pod on the kubernetes cluster:
```bash
curl http://kubeflow-pipelines-profile-controller:CONTROLLER_PORT/sync -d '{"parent":{"metadata":{"name":"someName","labels":{"pipelines.kubeflow.org/enabled":"true"}}},"children":{"Secret.v1":[],"ConfigMap.v1":[],"Deployment.apps/v1":[],"Service.v1":[],"DestinationRule.networking.istio.io/v1alpha3":[],"AuthorizationPolicy.security.istio.io/v1beta1":[]}}'
```

This mimics what Metacontroller will send the kubeflow-pipelines-profile-controller, ad JSON blob of:
* parent: JSON of the namespace that triggered this reconciliation loop
* children: JSON of the children of this reconciliation loop (eg: the children objects it is ensuring ecist).  In this case, we send empty lists which will require reconciliation.

Returned will be a JSON blob for the desired state of the children. 
