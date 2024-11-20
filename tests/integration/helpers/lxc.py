import sh
import jq

def clean_charmcraft_lxc_instances() -> None:
    """
    Delete lxc instances in project "charmcraft" that are prefixed with "charmcraft-".

    Based on https://discourse.charmhub.io/t/how-to-quickly-clean-unused-lxd-instances-from-charmcraft-pack/15975
    """
    lxc_instances = sh.lxc.list(project="charmcraft", format="json")
    lxc_instances_charmcraft = jq.compile('.[] | select(.name | startswith("charmcraft-")) | .name').input_text(lxc_instances).all()
    for instance in lxc_instances_charmcraft:
        print(f"Deleting lxc instance '{instance}'")
        sh.lxc.delete(instance, project="charmcraft")
