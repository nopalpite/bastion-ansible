import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "webui" / "app.py"
_spec = importlib.util.spec_from_file_location("bastion_ansible_webui", _MODULE_PATH)
webui = importlib.util.module_from_spec(_spec)
sys.modules["bastion_ansible_webui"] = webui
_spec.loader.exec_module(webui)


def make_client(tmp_path, monkeypatch):
    roles_dir = tmp_path / "roles"
    runs_dir = tmp_path / "runs"
    order_path = tmp_path / "order.yaml"
    site_path = tmp_path / "site.yml"
    monkeypatch.setattr(webui, "ROLES_DIR", roles_dir)
    monkeypatch.setattr(webui, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(webui, "RUNS_INDEX", runs_dir / "index.yaml")
    monkeypatch.setattr(webui, "ORDER_PATH", order_path)
    monkeypatch.setattr(webui, "SITE_YML", site_path)
    monkeypatch.setattr(webui.scaffold_roles, "ROLES_DIR", roles_dir)
    monkeypatch.setattr(webui.scaffold_roles, "ORDER_PATH", order_path)
    monkeypatch.setattr(webui.scaffold_roles, "SITE_PATH", site_path)
    webui.app.config["TESTING"] = True
    return webui.app.test_client()


def test_api_roles_list_reports_missing_tags(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "common" / "tasks").mkdir(parents=True)

    monkeypatch.setattr(
        webui.bastion_inventory,
        "fetch_machines",
        lambda: [{"id": 1, "name": "kiosk-01", "host": "10.0.0.11", "tags": ["common", "new-tag"]}],
    )

    res = client.get("/api/roles")
    data = res.get_json()

    assert res.status_code == 200
    assert data["roles"] == ["common"]
    assert data["missing_tags"] == ["new-tag"]
    assert data["bastion_error"] is None


def test_api_roles_list_reports_bastion_error(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    def raise_exit():
        raise SystemExit(1)

    monkeypatch.setattr(webui.bastion_inventory, "fetch_machines", raise_exit)

    res = client.get("/api/roles")
    data = res.get_json()

    assert res.status_code == 200
    assert data["bastion_error"] is not None
    assert data["missing_tags"] == []


def test_role_files_list_returns_all_files_recursively(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    role_dir = tmp_path / "roles" / "desktop"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n")
    (role_dir / "templates").mkdir(parents=True)
    (role_dir / "templates" / "foo.service.j2").write_text("[Unit]\n")

    res = client.get("/api/roles/desktop/files")

    assert res.status_code == 200
    assert res.get_json()["files"] == ["tasks/main.yml", "templates/foo.service.j2"]


def test_role_file_get_and_put_roundtrip(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    role_dir = tmp_path / "roles" / "desktop"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n")

    res = client.get("/api/roles/desktop/file/tasks/main.yml")
    assert res.status_code == 200
    assert res.get_json()["content"] == "---\n"

    res = client.put(
        "/api/roles/desktop/file/tasks/main.yml",
        json={"content": "---\n- name: exemple\n  debug:\n    msg: hello\n"},
    )
    assert res.status_code == 200
    assert (role_dir / "tasks" / "main.yml").read_text() == "---\n- name: exemple\n  debug:\n    msg: hello\n"


def test_role_file_put_creates_new_file_including_parent_dirs(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "desktop").mkdir(parents=True)

    res = client.put(
        "/api/roles/desktop/file/templates/foo.service.j2",
        json={"content": "[Unit]\nDescription=test\n"},
    )

    assert res.status_code == 200
    assert (tmp_path / "roles" / "desktop" / "templates" / "foo.service.j2").read_text() == "[Unit]\nDescription=test\n"


def test_role_file_put_rejects_invalid_yaml_for_yaml_files(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    role_dir = tmp_path / "roles" / "desktop"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n")

    res = client.put("/api/roles/desktop/file/tasks/main.yml", json={"content": "key: [unclosed"})

    assert res.status_code == 400
    assert (role_dir / "tasks" / "main.yml").read_text() == "---\n"


def test_role_file_put_does_not_validate_yaml_for_non_yaml_files(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "desktop").mkdir(parents=True)

    res = client.put(
        "/api/roles/desktop/file/templates/foo.j2",
        json={"content": "key: [unclosed - pas du YAML, un template Jinja2"},
    )

    assert res.status_code == 200


def test_resolve_role_file_rejects_path_traversal(tmp_path, monkeypatch):
    # Teste directement la fonction plutot que via HTTP : le client de
    # test/les libs WSGI normalisent souvent ".." dans l'URL avant meme
    # d'atteindre la route, ce qui masquerait un bug ici.
    make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "desktop").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("ne doit pas etre lisible")

    assert webui.resolve_role_file("desktop", "../secret.txt") is None
    assert webui.resolve_role_file("desktop", "../../secret.txt") is None
    assert webui.resolve_role_file("desktop", "tasks/main.yml") is not None


def test_role_file_delete_removes_file(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    role_dir = tmp_path / "roles" / "desktop"
    (role_dir / "handlers").mkdir(parents=True)
    (role_dir / "handlers" / "main.yml").write_text("---\n")

    res = client.delete("/api/roles/desktop/file/handlers/main.yml")

    assert res.status_code == 200
    assert not (role_dir / "handlers" / "main.yml").exists()


def test_scaffold_creates_role_from_tag(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    res = client.post("/api/roles/raspberry-pi/scaffold")
    data = res.get_json()

    assert res.status_code == 201
    assert data["role"] == "raspberry_pi"
    assert (tmp_path / "roles" / "raspberry_pi" / "tasks" / "main.yml").exists()
    assert webui.scaffold_roles.load_order() == ["raspberry_pi"]
    assert (tmp_path / "site.yml").exists()


def test_api_order_get_returns_current_order(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "a").mkdir(parents=True)
    (tmp_path / "roles" / "b").mkdir(parents=True)
    webui.scaffold_roles.save_order(["a", "b"])

    res = client.get("/api/order")

    assert res.get_json()["order"] == ["a", "b"]


def test_api_order_put_reorders_and_regenerates_site_yml(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "a").mkdir(parents=True)
    (tmp_path / "roles" / "b").mkdir(parents=True)
    webui.scaffold_roles.save_order(["a", "b"])

    res = client.put("/api/order", json={"order": ["b", "a"]})

    assert res.status_code == 200
    assert webui.scaffold_roles.load_order() == ["b", "a"]
    plays = webui.yaml.safe_load((tmp_path / "site.yml").read_text())
    assert [p["hosts"] for p in plays] == ["b", "a"]


def test_api_order_put_rejects_mismatched_role_set(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    (tmp_path / "roles" / "a").mkdir(parents=True)

    res = client.put("/api/order", json={"order": ["a", "unknown"]})

    assert res.status_code == 400


def test_scaffold_rejects_invalid_tag(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    res = client.post("/api/roles/Not Valid!/scaffold")

    assert res.status_code == 400


def test_runs_create_rejects_when_already_running(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(webui, "RUN_STATE", {"running": True})

    res = client.post("/api/runs", json={})

    assert res.status_code == 409


def test_execute_run_appends_extra_args_from_env(tmp_path, monkeypatch):
    make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("BASTION_ANSIBLE_EXTRA_ARGS", "--extra-vars ansible_become_pass=raspberry")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr(webui.subprocess, "run", fake_run)

    webui.execute_run("20260101T000000Z", "gpio")

    assert captured["cmd"][-4:] == ["--limit", "gpio", "--extra-vars", "ansible_become_pass=raspberry"]
