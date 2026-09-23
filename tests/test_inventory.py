import importlib.util
import sys
from pathlib import Path

# bastion_inventory.py n'est pas un package installable (juste un script
# d'inventaire Ansible autonome) - charge directement depuis son chemin
# plutot que d'ajouter un __init__.py qui n'aurait aucun autre role.
_MODULE_PATH = Path(__file__).resolve().parent.parent / "inventory" / "bastion_inventory.py"
_spec = importlib.util.spec_from_file_location("bastion_inventory", _MODULE_PATH)
bastion_inventory = importlib.util.module_from_spec(_spec)
sys.modules["bastion_inventory"] = bastion_inventory
_spec.loader.exec_module(bastion_inventory)


def test_group_name_normalizes_invalid_characters():
    assert bastion_inventory.group_name("raspberry-pi") == "raspberry_pi"
    assert bastion_inventory.group_name("kiosk") == "kiosk"
    assert bastion_inventory.group_name("  ") == "sans_tag"


def test_build_inventory_groups_by_tag():
    machines = [
        {"id": 1, "name": "kiosk-01", "host": "10.0.0.11", "os": "linux", "ssh_port": 22, "site": "salle-A", "tags": ["kiosk", "raspberry-pi"]},
        {"id": 2, "name": "reception-pc", "host": "10.0.0.20", "os": "windows", "site": "accueil", "tags": ["reception"]},
    ]

    inventory = bastion_inventory.build_inventory(machines)

    assert inventory["kiosk"]["hosts"] == ["kiosk-01"]
    assert inventory["raspberry_pi"]["hosts"] == ["kiosk-01"]
    assert inventory["reception"]["hosts"] == ["reception-pc"]

    hostvars = inventory["_meta"]["hostvars"]["kiosk-01"]
    assert hostvars["ansible_host"] == "10.0.0.11"
    assert hostvars["ansible_port"] == 22
    assert hostvars["bastion_os"] == "linux"
    assert hostvars["bastion_site"] == "salle-A"


def test_build_inventory_machine_without_tags_has_no_group():
    machines = [{"id": 3, "name": "no-tag-box", "host": "10.0.0.30", "tags": []}]

    inventory = bastion_inventory.build_inventory(machines)

    assert "no-tag-box" in inventory["_meta"]["hostvars"]
    groups = {k: v for k, v in inventory.items() if k != "_meta"}
    assert all("no-tag-box" not in g["hosts"] for g in groups.values())


def test_build_inventory_omits_absent_optional_fields():
    machines = [{"id": 4, "name": "bare-box", "host": "10.0.0.40", "tags": []}]

    hostvars = bastion_inventory.build_inventory(machines)["_meta"]["hostvars"]["bare-box"]

    assert "ansible_port" not in hostvars
    assert "bastion_os" not in hostvars
    assert "bastion_site" not in hostvars
