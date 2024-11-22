import sh

def charmcraft_clean(charms_paths: list[str]) -> None:
    """
    Run `charmcraft clean` for passed paths to charms.
    """
    for charm_path in charms_paths:
        sh.cd(charm_path)
        sh.charmcraft.clean()
        sh.cd("-")
