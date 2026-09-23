import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "scaffold_roles.py"
_spec = importlib.util.spec_from_file_location("scaffold_roles", _MODULE_PATH)
scaffold_roles = importlib.util.module_from_spec(_spec)
sys.modules["scaffold_roles"] = scaffold_roles
_spec.loader.exec_module(scaffold_roles)


def patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold_roles, "ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(scaffold_roles, "ORDER_PATH", tmp_path / "order.yaml")
    monkeypatch.setattr(scaffold_roles, "SITE_PATH", tmp_path / "site.yml")


def test_scaffold_creates_expected_files(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)

    scaffold_roles.scaffold("kiosk")

    assert (tmp_path / "roles" / "kiosk" / "tasks" / "main.yml").exists()
    assert (tmp_path / "roles" / "kiosk" / "defaults" / "main.yml").exists()
    assert (tmp_path / "roles" / "kiosk" / "meta" / "main.yml").exists()


def test_scaffold_does_not_overwrite_existing_files(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    tasks = tmp_path / "roles" / "kiosk" / "tasks" / "main.yml"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("custom content")

    scaffold_roles.scaffold("kiosk")

    assert tasks.read_text() == "custom content"


def test_scaffold_appends_to_order_and_renders_site_yml(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)

    scaffold_roles.scaffold("kiosk")

    assert scaffold_roles.load_order() == ["kiosk"]
    plays = scaffold_roles.yaml.safe_load((tmp_path / "site.yml").read_text())
    assert plays[0]["roles"] == ["kiosk"]


def test_scaffold_does_not_duplicate_order_entry(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    scaffold_roles.scaffold("kiosk")

    scaffold_roles.scaffold("kiosk")

    assert scaffold_roles.load_order() == ["kiosk"]


def test_main_scaffolds_tags_from_api(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        scaffold_roles.bastion_inventory,
        "fetch_machines",
        lambda: [{"id": 1, "name": "kiosk-01", "host": "10.0.0.11", "tags": ["kiosk"]}],
    )

    scaffold_roles.main()

    assert (tmp_path / "roles" / "kiosk" / "tasks" / "main.yml").exists()
    assert scaffold_roles.load_order() == ["kiosk"]


def test_main_skips_tags_that_already_have_a_role(tmp_path, monkeypatch, capsys):
    patch_paths(tmp_path, monkeypatch)
    (tmp_path / "roles" / "kiosk").mkdir(parents=True)
    monkeypatch.setattr(
        scaffold_roles.bastion_inventory,
        "fetch_machines",
        lambda: [{"id": 1, "name": "kiosk-01", "host": "10.0.0.11", "tags": ["kiosk"]}],
    )

    scaffold_roles.main()

    assert "Aucun nouveau tag" in capsys.readouterr().out
