import logging
from os import chdir
from pathlib import Path
from typing import Dict

from kfp_globals import basedir

import sh

log = logging.getLogger(__name__)


def charmcraft_clean(charms_paths: Dict[str, Path]) -> None:
    """
    Run `charmcraft clean` for passed paths to charms.
    """
    pwd = sh.pwd()
    for charm, charm_path in charms_paths.items():
        log.info(f"Charmcraft clean {charm}")
        chdir(charm_path)
        sh.charmcraft.clean()
    # Return to original directory so it doesn't affect tests execution
    chdir(pwd)
