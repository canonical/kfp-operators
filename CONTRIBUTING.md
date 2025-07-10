## Update manifests

KFP charms use Jinja2 templates in order to store manifests that are applied during its deployment. Those manifests are placed under `src/templates` in each charm's directory. The process for updating them is:

### Spot the differences between versions of a manifest file

1. Install `kustomize` using the official documentation [instructions](https://kubectl.docs.kubernetes.io/installation/kustomize/)
2. Clone [Kubeflow manifests](https://github.com/kubeflow/manifests) repo locally
3. `cd` into the repo and checkout to the branch or tag of the target version.
4. Build the manifests with `kustomize` according to instructions in https://github.com/kubeflow/manifests?tab=readme-ov-file#kubeflow-pipelines.
5. Checkout to the branch or tag of the version of the current manifest
6. Build the manifest with `kustomize` (see step 4) and save the file
7. Compare both files to spot the differences (e.g. using diff `diff kfp-manifests-vX.yaml kfp-manifests-vY.yaml > kfp-vX-vY.diff`)

### Spot the updated images used by kfp-api

Kfp-api uses also two images `launcher` and `driver` apart from its workload container one. Those are updated on every release but this change is not visible when comparing manifests. In order to update those, grab their sources from the corresponding comments in the [config.yaml](./charms/kfp-api/config.yaml) file and switch to the target version of that file. Then, use the new images to update the config options' default value. 

### Introduce changes

Once the comparison is done, add any changes to the relevant aggregated ClusterRoles to the
  `templates/auth_manifests.yaml.j2` file and remember to:
  * Use the current model as the namespace
  * Use the application name in the name of any ClusterRoles, ClusterRoleBindings, or ServiceAccounts.
  * Add to the labels `app: {{ app_name }}`

Note that non-aggregated ClusterRoles are skipped due to deploying charms with the `--trust` argument. Regarding CRDs that have updates, they are copied as they are into the corresponding charm's in a `crds.yaml.j2` file while there can be changes in other resources as well e.g. `secrets` or `configMaps`.

### Things to pay attention
* In order to copy kfp-profile-controller CRDs, follow instructions on the top of its [crd_manifests.yaml.j2](./charms/kfp-profile-controller/src/templates/crd_manifests.yaml.j2) file.
* We do not have a `cache-server` component, so related manifests are skipped.
* We do not keep a `pipeline-runner` `ServiceAccount` (and related manifests), since even though the api-server is [configured to use it by default](https://github.com/kubeflow/pipelines/blob/dd59f48cdd0f6cd7fac40306277ef5f3dad6e263/backend/src/apiserver/config/config.json#L23), the manifests update it to [use a different one](https://github.com/kubeflow/manifests/blob/8ea40590cc12bdd6a3aa6367741ddb68f52073cb/apps/pipeline/upstream/base/installs/multi-user/api-service/params.env#L2). 
* For argo related manifests, we only keep the `aggregate` `ClusterRole`s.
* Apart from changes shown in the `diff` above, kfp-api charm also requires updating `driver-image` and `launcher-image` values in the [config](./config.yaml) file. Source for those can be found in the charm's [config.yaml](./charms/kfp-api/config.yaml) file.
* Changes for [envoy](https://github.com/canonical/envoy-operator) charm may also be included in the aforementioned `diff`.
* We do not keep a `pipeline-install-config` `configMap` as upstream does, since charms define those configurations either in their `config.yaml` or directly in their pebble layer. However, we should pay attention to changes in that `configMap`'s values since its values could be used in other places, using the `valueFrom` field in an `env`'s definition.


## How to Manage Python Dependencies and Environments


### Prerequisites

`tox` is the only tool required locally, as `tox` internally installs and uses `poetry`, be it to manage Python dependencies or to run `tox` environments. To install it: `pipx install tox`.

Optionally, `poerty` can be additionally installed independently just for the sake of running Python commands locally outside of `tox` during debugging/development. To install it: `pipx install poetry`.


### Updating Dependencies

To add/update/remove any dependencies and/or to upgrade Python, simply:

1. add/update/remove such dependencies to/in/from the desired group(s) below `[tool.poetry.group.<your-group>.dependencies]` in `pyproject.toml`, and/or upgrade Python itself in `requires-python` under `[project]`

    _⚠️ dependencies for the charm itself are also defined as dependencies of a dedicated group called `charm`, specifically below `[tool.poetry.group.charm.dependencies]`, and not as project dependencies below `[project.dependencies]` or `[tool.poetry.dependencies]` ⚠️_

2. run `tox -e update-requirements` to update the lock file

    by this point, `poerty`, through `tox`, will let you know if there are any dependency conflicts to solve.

3. optionally, if you also want to update your local environment for running Python commands/scripts yourself and not through tox, see [Running Python Environments](#running-python-environments) below


### Running `tox` Environments

To run `tox` environments, either locally for development or in CI workflows for testing, ensure to have `tox` installed first and then simply run your `tox` environments natively (e.g.: `tox -e lint`). `tox` will internally first install `poetry` and then rely on it to install and run its environments.


### Running Python Environments

To run Python commands locally for debugging/development from any environments built from any combinations of dependency groups without relying on `tox`:
1. ensure you have `poetry` installed
2. install any required dependency groups: `poetry install --only <your-group-a>,<your-group-b>` (or all groups, if you prefer: `poetry install --all-groups`)
3. run Python commands via poetry: `poetry run python3 <your-command>`
