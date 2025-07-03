# `kfp-operators` integration tests

This directory contains a number of test suites for testing the `kfp-operators` in different configurations and integrated with other charms that belong to the Charmed Kubeflow bundle.

### Direcroty structure

This directory has the following structure:

```
.
├── README.md
└── integration
    ├── bundles
    │   └── bundle.yaml.j2
    ├── conftest.py
    ├── helpers
    │   ├── bundle_mgmt.py
    │   ├── charmcraft.py
    │   ├── k8s_resources.py
    │   └── localize_bundle.py
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
* charmcraft (only for testing the charms locally using option A)
* charmcraftcache (only for testing the charms locally using option B)
* tox
* lxd (only for testing with locally built and if `destructive-mode` is not enabled)

#### Functional tests

The test suite for functional tests will deploy the `bundle.yaml.j2` bundle, upload a pipeline, create an experiment, create a run and a recurring run, and run health checks on the visualisation and viewer servers.
Communication with the KFP API happens using the KFP Python SDK. A `kfp.client` is configured using a test profile (`Profile`) to be able to execute pipeline operations (create runs, experiments, upload pipelines, etc.).

> NOTE: This test suite does not deploy the `kfp-profile-controller` as the tests for that component are already covered in the charm's directory.

1. Create a `kubeflow` model with `juju add-model kubeflow`
2. Run integration tests against the preferred bundle definition in `integration/bundles`

    Option A - Build charms with charmcraft

    * Install charmcraft
    * Run the tests with the command:
    ```
    tox -e bundle-integration -- --model kubeflow --bundle=./tests/integration/bundles/<bundle_template> <--charmcraft-clean>
    ```
    This builds the charms sequentially with `charmcraft` through `ops_test.build_charm`, then deploys them.

    Option B - Build charms with ccc
    * Install [charmcraftcache](https://github.com/canonical/charmcraftcache?tab=readme-ov-file#installation)
    * Go into each charm directory and pack the charm with `ccc`. For example:
    ```
    cd charms/kfp-api
    ccc pack
    ```
    * Run the tests with the command:
    ```
    tox -e bundle-integration -- --model kubeflow --bundle=./tests/integration/bundles/<bundle_template> --charms-path /charms/
    ```
    This immediately deploys the charms packed with `ccc` before running the tests.

Where,
* `--model` tells the testing framework which model to deploy charms to
* `--bundle` is the path to a bundle template that's going to be used during the test execution
* `--charms-path` is the path to the built charms when using option B
* `--charmcraft-clean` tells the test suite whether to run `charmcraft clean` and delete the lxc instances after building the charms. If `--charms-path` is passed, this has no effect.
