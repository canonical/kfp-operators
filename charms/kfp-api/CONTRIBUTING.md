# Contributing

## Overview

This document outlines the processes and practices recommended for contributing enhancements to `kfp-api`.

## Talk to us First

Before developing enhancements to this charm, you should [open an issue](/../../issues) explaining your use case. If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [MLOps Mattermost public channel](https://chat.charmhub.io/charmhub/channels/mlops-documentation) or on [Discourse](https://discourse.charmhub.io/).

## Pull Requests

Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

All pull requests require review before being merged. Code review typically examines:
  - code quality
  - test coverage
  - user experience for Juju administrators of this charm.

## Recommended Knowledge

Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.

## Build Charm

To build `kfp-api` run:

```shell
charmcraft pack
```

## Developing

You can use the environments created by `tox` for development. For example, to load the `unit` environment into your shell, run:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Testing

Use tox for testing. For example to test the `integration` environment, run:

```shell
tox -e integration
```

See `tox.ini` for all available environments.

### Deploy

```bash
# Create a model
juju add-model dev
# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"
# Deploy the charm
juju deploy ./kfp-api_ubuntu@24.04-amd64.charm \
    --resource oci-image=$(yq '.resources."oci-image"."upstream-source"' metadata.yaml)

## Canonical Contributor Agreement

Canonical welcomes contributions to this charm. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing.