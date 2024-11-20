# `kfp-operators` integration tests

This directory contains a number of test suites for testing the `kfp-operators` in different configurations and integrated with other charms that belong to the Charmed Kubeflow bundle.

### Direcroty structure

This directory has the following structure:

```
.
├── README.md
└── integration
    ├── bundles
    |   ├── kfp_1.8_stable_install.yaml.j2
    │   ├── kfp_1.7_stable_install.yaml.j2
    │   └── kfp_latest_edge.yaml.j2
    ├── conftest.py
    ├── helpers
    │   ├── bundle_mgmt.py
    │   ├── k8s_resources.py
    │   └── localize_bundle.py
    │   └── lxc.py
    ├── kfp_globals.py
    ├── pipelines/
    │   └── ... # Sample pipelines
    ├── profile
    │   └── profile.yaml
    ├── test_kfp_functional.py
    └── viewer
        └── mnist.yaml
```

* `integration/bundles`: contains a set of bundle definition Jinja2 templates that can be passed to the `tox` command to run integration tests against different configurations for the kfp-operators. The CI runs the latest stable version of this bundle definition by default.
* `integration/pipelines`: contains Python scripts that define KFP pipelines, these are used to compile the pipelines files (YAML files inside this same directory). These files are used by the test suites for uploading pipelines and creating runs, for instance.
* `integration/viewer`: contains a set of `Viewer` objects that can be used to test the Visualisation (kfp-viz) and Viewer (kfp-viewer) KFP componets.
* `integration/helpers`: contains a set of helper methods that are used by the test suites.

## Testing locally

#### Pre-requisites and assumptions

* It is assumed these tests will run in a Microk8s environment.
* Microk8s addons: metallb, hostpath-storage, dns
> NOTE: Metallb is enabled with an arbitrary IP range 10.64.140.43-10.64.140.49
* juju
* charmcraft (only for testing with locally built charms)
* tox
* lxd (only for testing with locally built and if `destructive-mode` is not enabled)

#### Functional tests

The test suite for functional tests will deploy the `kfp_1.7_stable_install.yaml.j2` bundle, upload a pipeline, create an experiment, create a run and a recurring run, and run health checks on the visualisation and viewer servers.
Communication with the KFP API happens using the KFP Python SDK. A `kfp.client` is configured using a test profile (`Profile`) to be able to execute pipeline operations (create runs, experiments, upload pipelines, etc.).

> NOTE: This test suite does not deploy the `kfp-profile-controller` as the tests for that component are already covered in the charm's directory.

1. Create a `kubeflow` model with `juju add-model kubeflow`
2. Run integration tests against the preferred bundle definition in `integration/bundles`

```
tox -e bundle-integration -- --model kubeflow --bundle=./tests/integration/bundles/<bundle_template> <--no-build> <--clean-lxc-instances>
```

Where,
* `--model` tells the testing framework which model to deploy charms to
* `--bundle` is the path to a bundle template that's going to be used during the test execution
* `--no-build` tells the test suite whether to build charms and run tests against them, or use charms in Charmhub
* `--no-build` tells the test suite whether to build charms and run tests against them, or use charms in Charmhub
* `--clean-lxc-instances` tells the test suite whether to delete lxc instances after building and deploying the charms. If `--no-build` is passed, then this has no effect.
