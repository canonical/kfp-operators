# `kfp-operators` integration tests

This directory contains a number of test suites for testing the `kfp-operators` in different configurations and integrated with other charms that belong to the Charmed Kubeflow bundle.

### Direcroty structure

This directory has the following structure:

```
.
├── README.md
├── conftest.py
└── integration
    ├── bundles
    │   ├── kfp_1.7_stable_generic_install.yaml.j2
    │   └── kfp_latest_edge.yaml.j2
    ├── helpers
    │   ├── bundle_mgmt.py
    │   └── localize_bundle.py
    ├── pipelines
    │   ├── sample_pipeline.yaml
    │   └── sample_pipeline_execution_order.py
    ├── test_kfp_generic_installation.py
    └── viewer
        └── mnist.yaml
```

* `integration/bundles`: contains a set of bundle definition Jinja2 templates that can be passed to the `tox` command to run integration tests against different configurations for the kfp-operators. The CI runs the latest stable version of this bundle definition.
* `integration/pipelines`: contains Python scripts that define KFP pipelines, these are used to compile the pipelines files (YAML files inside this same directory). These files are used by the test suites for uploading pipelines and creating runs, for instance.
* `integration/viewer`: contains a set of `Viewer` objects that can be used to test the Visualisation (kfp-viz) and Viewer (kfp-viewer) KFP componets.
* `integration/helpers`: contains a set of helper methods that are used by the test suites.

## Testing a "generic" installation

### Pre-requisites and assumptions

* It is assumed these tests will run in a Microk8s environment.
* Microk8s addons: metallb, hostpath-storage, dns
> NOTE: Metallb is enabled with an arbitrary IP range 10.64.140.43-10.64.140.49
* juju
* charmcraft (only for local builds)
* tox
* lxd (only for local builds and if `destructive-mode` is not enabled)

##### Testing locally

1. Create a `kubeflow` model with `juju add-model kubeflow`
2. Run integration tests against the preferred bundle definition in `integration/bundles`

```
tox -e bundle-integration -- --model kubeflow --bundle=./tests/integration/bundles/<bundle_template> --build=<true|false>
```

Where,
* `--model` tells the testing framework which model to deploy charms to
* `--bundle` is the path to a bundle template that's going to be used during the test execution
* `--build` tells the test suite whether to build charms and run tests against them, or use charms in Charmhub

## Testing a multi-user installation
TODO
