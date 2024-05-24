## Update manifests

KFP charms use Jinja2 templates in order to store manifests that need to be applied during its deployment. The process for updating them is:

### Spot the differences between versions of a manifest file

1. Install `kustomize` using the official documentation [instructions](https://kubectl.docs.kubernetes.io/installation/kustomize/)
2. Clone [Kubeflow manifests](https://github.com/kubeflow/manifests) repo locally
3. `cd` into the repo and checkout to the branch or tag of the target version.
4. Build the manifests with `kustomize` and save the file:

```bash
kustomize build apps/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user > kfp-manifests-vX.yaml
```

5. Checkout to the branch or tag of the version of the current manifest
6. Build the manifest with `kustomize` (see step 4) and save the file
7. Compare both files to spot the differences (e.g. using diff `diff kfp-manifests-vX.yaml kfp-manifests-vY.yaml > kfp-vX-vY.diff`)

### Introduce changes

Once the comparison is done, add any changes to the relevant ClusterRoles and ClusterRoleBindings to the
  `templates/auth_manifests.yaml.j2` file and remember to:
  * Use the current model as the namespace
  * Use the application name in the name of any ClusterRoles, ClusterRoleBindings, or ServiceAccounts.
  * Add to the labels `app: {{ app_name }}`


### Things to pay attention
* We do not have a `cache-server` component, so related manifests are skipped.
* We do not keep a `pipeline-runner` `ServiceAccount` (and related manifests), since even though the api-server is [configured to use it by default](https://github.com/kubeflow/pipelines/blob/dd59f48cdd0f6cd7fac40306277ef5f3dad6e263/backend/src/apiserver/config/config.json#L23), the manifests update it to [use a different one](https://github.com/kubeflow/manifests/blob/8ea40590cc12bdd6a3aa6367741ddb68f52073cb/apps/pipeline/upstream/base/installs/multi-user/api-service/params.env#L2). 
* For argo related manifests, we only keep the `aggregate` `ClusterRole`s.
* Apart from changes shown in the `diff` above, this charm also requires updating `driver-image` and `launcher-image` values in the [config](./config.yaml) file. Source for this can be found there
* Changes for [envoy](https://github.com/canonical/envoy-operator) charm may also be included in the aforementioned `diff`.
* We do not keep a `pipeline-install-config` `configMap` as upstream does, since charms define those configurations either in their `config.yaml` or directly in their pebble layer. However, we should pay attention to changes in that `configMap`'s values since its values could be used in other places, using the `valueFrom` field in an `env`'s definition.
