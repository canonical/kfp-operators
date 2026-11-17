# AGENTS.md

Juju Kubernetes charms (Python, `ops`) for Kubeflow Pipelines, plus the bundle that composes
them. Each directory under `charms/` is a separate charm with its own `pyproject.toml`,
`poetry.lock`, `tox.ini`, terraform module, and tests. The root holds `bundle.yaml`, bundle-level
integration tests in `tests/`, and CI in `.github/workflows/`.

The human contributor docs are the source of truth. Read them before the matching kind of change:
root `CONTRIBUTING.md` (manifest updates, dependencies, bundle tests), and the charm's own
`README.md`, `CONTRIBUTING.md` and `tests/README.md`.

## Commands

All tooling goes through `tox`, which installs `poetry` itself. Do not call `pip` or create virtualenvs by hand.

```sh
# From a charm directory, e.g. charms/kfp-api
tox -e fmt                                          # isort + black (writes files)
tox -e lint                                         # codespell, pflake8, isort, black (check only)
tox -e unit                                         # unit tests with coverage
tox -e unit -- tests/unit/test_operator.py::test_x  # a single test
tox -e tflint                                       # terraform module lint (needs tflint)
charmcraft pack                                     # build the .charm (slow; only when needed)

# From the repo root
tox -e kfp-api-unit        # proxy: run <charm>-<env> without cd (see envlist in root tox.ini)
tox -e lint                # lints only the root tests/ directory
```

Integration environment names differ per charm (`integration`, `integration-s3`,
`integration-object-storage`, `integration-ambient`). Read the charm's `tox.ini` to find them.

## Workflow

1. Work in the charm that owns the behaviour. If a change spans several charms, change and
   validate each one in its own directory.
2. Run `tox -e fmt`, then `tox -e lint` and `tox -e unit` for every charm you touched. CI runs
   the same lint and unit environments for all eight charms.
3. Add or update unit tests for behaviour changes in the charm's `tests/unit/`.
4. Before handing off, review the diff for unrelated or generated changes (`.coverage`,
   `*.charm`, `build/`). Report which checks you ran and which you skipped, and why.

## Conventions

- **Charm structure:** most charms build their logic from `charmed_kubeflow_chisme` components:
  a `CharmReconciler` in `src/charm.py` with components in `src/components/`. `kfp-api` predates
  this and uses imperative handlers. Follow the style of the charm you are editing, and do not
  migrate a charm to the other style unless asked.
- **Unit tests:** use `ops.testing.Harness`, following the existing
  `tests/unit/test_operator.py`. Mock Kubernetes (`lightkube`) calls and never reach a real cluster.
- **Integration tests:** use `pytest-operator` (`ops_test`). Pin dependency charms as `CharmSpec`
  entries in `tests/integration/charms_dependencies.py`, not inline in test files.
- **New Python files:** start with the two-line header
  `# Copyright <year> Canonical Ltd.` / `# See LICENSE file for licensing details.`
- **Commits and PR titles:** use Conventional Commits (`feat:`, `fix:`, `chore:`, `ci:`, `test:`,
  `docs:`). Scope with the charm name when only one charm changes, for example
  `fix(kfp-ui): ...`.

## Public interfaces

Juju users and other charms depend on these, so treat them as public API. Do not rename or
remove them, or change their meaning, unless the task explicitly asks for it. If it does, state
the breaking change in the handoff.

- Relation endpoints in `metadata.yaml`, config options and defaults in `config.yaml`, and
  `resources`.
- Endpoint names are repeated in `terraform/outputs.tf` (`provides`/`requires`), `bundle.yaml`,
  and `tests/integration/bundles/`. Update every copy together.

## Gotchas

- **Vendored charm libraries:** `charms/*/lib/charms/` holds libraries owned by other charms and
  fetched from Charmhub. Never edit them by hand. Update with
  `charmcraft fetch-lib charms.<owner>.<vN>.<lib>` from the charm directory. When a library is
  vendored in several charms, keep them on the same `LIBPATCH`.
- **Dependencies:** charm runtime dependencies go in `[tool.poetry.group.charm.dependencies]`, not
  in `[project.dependencies]`. Never edit `poetry.lock` by hand. Regenerate it with
  `tox -e update-requirements` in the affected charm, and only when the task needs a dependency
  change. Renovate handles routine bumps.
- **Manifest templates:** files under `src/templates/` are adapted from upstream
  `kubeflow/manifests`. The `# Source` comments and inline comments mark deliberate deviations
  from upstream, for example `updateStrategy: InPlace` in `kfp-profile-controller`. Keep them.
  For upstream version bumps, follow the "Update manifests" section of root `CONTRIBUTING.md`,
  which also covers the `driver-image` and `launcher-image` defaults in `kfp-api/config.yaml`.
- **Images:** workload images are the `upstream-source` values in `metadata.yaml` and the config
  options whose names end in `-image`. `tools/get-images.sh` discovers images by those two
  conventions, so keep them when adding an image.
- **Release tracks:** `main` publishes to `latest/edge`. `track/<version>` branches are stable
  tracks, and labels on PRs to `main` drive backports. Do not target or cherry-pick to a track
  branch unless asked. If a fix probably needs a backport, say so in the handoff.

## Boundaries

- **Always:** keep changes minimal and scoped to the request. Run the lint and unit checks above
  for each touched charm.
- **Ask first:** integration tests (`tox -e integration*`, `tox -e bundle-integration*`), or
  anything else that deploys to or changes a Juju model or Kubernetes cluster. These need a
  bootstrapped controller (see `concierge.yaml`) and can take a long time. Also ask before
  dependency or lockfile changes, edits to `.github/workflows/`, and changes to public
  interfaces.
- **Never:** put credentials, tokens or other secrets in source, tests, fixtures or logs. Never
  remove or modify resources in an existing Juju model or cluster that you did not create for
  the current task. Never push, release to Charmhub, or force-push.

## Keeping this file current

This file is for things an agent cannot infer from the code. When a convention changes, or an
agent repeats the same mistake, update this file in the same PR. Keep it short. If a charm
develops genuinely different rules, add a nested `charms/<charm>/AGENTS.md` that covers only the
differences.
