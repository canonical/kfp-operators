# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import copy
from pathlib import Path
from typing import Dict, Optional, Union
import yaml
from zipfile import ZipFile


# TODO: Move this somewhere more general


def get_charm_name(metadata_file: Union[Path, str]) -> str:
    metadata = yaml.safe_load(Path(metadata_file).read_text())
    return metadata["name"]


def get_charm_file(charm_dir: Path) -> Path:
    """Returns the path to the .charm file representing the charm in the given directory

    TODO: This just assumes the suffix on the file name will be "ubuntu-20.04-amd64".
          Fix this in future
    """
    charm_dir = Path(charm_dir)
    metadata_file = charm_dir / "metadata.yaml"
    charm_name = get_charm_name(metadata_file)

    return (charm_dir / f"{charm_name}_ubuntu-20.04-amd64.charm").absolute()


def get_resources_from_charm_dir(charm_dir: Path) -> Dict[str, str]:
    """Returns the resources of the charm at path"""
    metadata_file = charm_dir / "metadata.yaml"
    metadata = yaml.safe_load(Path(metadata_file).read_text())
    resources = metadata["resources"]
    return {k: v["upstream-source"] for k, v in resources.items()}


def get_resources_from_charm_file(charm_file: str) -> Dict[str, str]:
    """Extracts the resources of a charm from a .charm (zipped) file."""
    with ZipFile(charm_file, "r") as zip:
        metadata_file = zip.open("metadata.yaml")
        metadata = yaml.safe_load(metadata_file)
        resources = metadata["resources"]
        return {k: v["upstream-source"] for k, v in resources.items()}
    open_charm_file = charm_file


def localize_bundle_application(
    bundle: dict,
    application: str,
    charm_dir: Optional[Path] = None,
    charm_file: Optional[Path] = None,
    resources: Optional[dict] = None,
):
    """Localize an application in a bundle, replacing its charm and resource with local files

    TODO: better docstring
    charm_file and resources can optionally be provided, otherwise they will be inferred from
    charm_dir.  If we provide charm_file and not resources, resources will be inferred from the
    metadata.yaml file in the charm_file.
    """
    bundle = copy.deepcopy(bundle)

    if not (charm_file or charm_dir):
        raise ValueError("Either charm_file or charm_dir must be provided")

    if charm_file:
        if not resources:
            resources = get_resources_from_charm_file(charm_file)
    else:
        charm_file = get_charm_file(charm_dir)
        if not resources:
            resources = get_resources_from_charm_dir(charm_dir)

    bundle["applications"][application]["charm"] = f"./{charm_file}"
    bundle["applications"][application]["resources"] = resources
    bundle["applications"][application]["_channel"] = bundle["applications"][application][
        "channel"
    ]
    del bundle["applications"][application]["channel"]

    return bundle


def main(bundle_file: str, application: str, charm_dir: str, output_file: str):
    bundle = yaml.safe_load(Path(bundle_file).read_text())
    charm_dir = Path(charm_dir)
    output_bundle = localize_bundle_application(bundle, application, charm_dir)

    with open(output_file, "w") as fout:
        yaml.dump(output_bundle, fout)


if __name__ == "__main__":
    import typer

    typer.run(main)
