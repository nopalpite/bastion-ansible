#!/usr/bin/env python3
"""bastion-ansible webui : voir/editer les roles, declencher des runs.

Service supplementaire a cote du runner CLI (docker-compose.yml), pas un
remplacement - execute `ansible-playbook` lui-meme en subprocess (meme
technique que caddy-admin appelant render-caddyfile.py), pas besoin de
piloter un autre conteneur.

Pas d'authentification, comme le reste des apps admin de ce projet -
cette UI peut executer des taches (become: true) contre tout le parc
reference dans Bastion, protegee uniquement par l'isolation reseau de
son environnement de deploiement.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "inventory"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import bastion_inventory  # noqa: E402
import scaffold_roles  # noqa: E402

app = Flask(__name__)

ROLES_DIR = REPO_ROOT / "roles"
ROLES_SEED_DIR = Path("/opt/roles-seed")
RUNS_DIR = REPO_ROOT / "runs"
RUNS_INDEX = RUNS_DIR / "index.yaml"
SITE_YML = REPO_ROOT / "site.yml"
SSH_KEY_SRC = REPO_ROOT / "secrets" / "automation_ed25519"
SSH_KEY_RUN = Path("/tmp/automation_ed25519")

TAG_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")
ROLE_FILE_KEYS = {
    "tasks": "tasks/main.yml",
    "defaults": "defaults/main.yml",
    "meta": "meta/main.yml",
}

RUN_STATE = {"running": False}
RUN_LOCK = threading.Lock()


def seed_roles_if_empty() -> None:
    """Premiere execution sans checkout local (ex: expolab, roles/ monte
    vide) : copie la reference bakee a la construction de l'image. Ne
    touche jamais un roles/ deja peuple (checkout local en dev, ou un
    second demarrage dans un environnement deja seed)."""
    if ROLES_DIR.exists() and any(ROLES_DIR.iterdir()):
        return
    if not ROLES_SEED_DIR.exists():
        return
    ROLES_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROLES_SEED_DIR, ROLES_DIR, dirs_exist_ok=True)


def prepare_ssh_key() -> None:
    # Meme precaution que entrypoint.sh : un bind mount depuis
    # Windows/Docker Desktop expose souvent la cle avec des permissions
    # trop ouvertes, que ssh refuserait telles quelles.
    if not SSH_KEY_SRC.exists():
        return
    shutil.copy(SSH_KEY_SRC, SSH_KEY_RUN)
    SSH_KEY_RUN.chmod(0o600)
    os.environ["ANSIBLE_PRIVATE_KEY_FILE"] = str(SSH_KEY_RUN)


def local_roles() -> set[str]:
    if not ROLES_DIR.exists():
        return set()
    return {p.name for p in ROLES_DIR.iterdir() if p.is_dir()}


def fetch_tags_safe() -> tuple[list[str], str | None]:
    """bastion_inventory.fetch_machines() fait sys.exit(1) sur erreur
    (comportement voulu pour un script CLI) - intercepte pour ne jamais
    faire tomber une requete Flask."""
    try:
        machines = bastion_inventory.fetch_machines()
    except SystemExit:
        return [], "Impossible de joindre Bastion (verifier BASTION_URL/BASTION_API_TOKEN)."
    tags = sorted({t for m in machines for t in (m.get("tags") or [])})
    return tags, None


def load_runs() -> list[dict]:
    if not RUNS_INDEX.exists():
        return []
    with open(RUNS_INDEX) as f:
        return yaml.safe_load(f) or []


def save_runs(runs: list[dict]) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = RUNS_INDEX.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        yaml.safe_dump(runs, f, sort_keys=False)
    os.replace(tmp_path, RUNS_INDEX)


def execute_run(run_id: str, limit: str | None) -> None:
    log_path = RUNS_DIR / f"{run_id}.log"
    cmd = ["ansible-playbook", str(SITE_YML)]
    if limit:
        cmd += ["--limit", limit]
    try:
        with open(log_path, "w") as logf:
            result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=REPO_ROOT)
        status = "ok" if result.returncode == 0 else "failed"
    except Exception as exc:
        with open(log_path, "a") as logf:
            logf.write(f"\nErreur d'execution : {exc}\n")
        status = "failed"

    runs = load_runs()
    for r in runs:
        if r["id"] == run_id:
            r["status"] = status
            r["finished_at"] = datetime.now(timezone.utc).isoformat()
            break
    save_runs(runs)
    with RUN_LOCK:
        RUN_STATE["running"] = False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/roles", methods=["GET"])
def api_roles_list():
    roles = sorted(local_roles())
    tags, bastion_error = fetch_tags_safe()
    missing_tags = [t for t in tags if bastion_inventory.group_name(t) not in local_roles()]
    return jsonify({"roles": roles, "missing_tags": missing_tags, "bastion_error": bastion_error})


@app.route("/api/roles/<tag>/scaffold", methods=["POST"])
def api_roles_scaffold(tag: str):
    if not TAG_RE.match(tag):
        return jsonify({"error": "Tag invalide"}), 400
    role = bastion_inventory.group_name(tag)
    if role in local_roles():
        return jsonify({"error": f"'{role}' existe deja"}), 409
    scaffold_roles.scaffold(role)
    return jsonify({"ok": True, "role": role}), 201


@app.route("/api/roles/<role>/files", methods=["GET"])
def api_role_files_get(role: str):
    if not ROLE_NAME_RE.match(role) or role not in local_roles():
        return jsonify({"error": f"'{role}' introuvable"}), 404
    files = {}
    for key, rel_path in ROLE_FILE_KEYS.items():
        path = ROLES_DIR / role / rel_path
        files[key] = path.read_text() if path.exists() else ""
    return jsonify({"files": files})


@app.route("/api/roles/<role>/files/<key>", methods=["PUT"])
def api_role_files_put(role: str, key: str):
    if not ROLE_NAME_RE.match(role) or role not in local_roles():
        return jsonify({"error": f"'{role}' introuvable"}), 404
    if key not in ROLE_FILE_KEYS:
        return jsonify({"error": "Fichier invalide"}), 400

    body = request.get_json(force=True, silent=True) or {}
    content = body.get("content", "")
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return jsonify({"error": f"YAML invalide : {exc}"}), 400

    path = ROLES_DIR / role / ROLE_FILE_KEYS[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, path)
    return jsonify({"ok": True})


@app.route("/api/runs", methods=["GET"])
def api_runs_list():
    return jsonify({"runs": sorted(load_runs(), key=lambda r: r["started_at"], reverse=True)})


@app.route("/api/runs", methods=["POST"])
def api_runs_create():
    with RUN_LOCK:
        if RUN_STATE["running"]:
            return jsonify({"error": "Un run est deja en cours"}), 409
        RUN_STATE["running"] = True

    body = request.get_json(force=True, silent=True) or {}
    limit = (body.get("limit") or "").strip() or None

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs = load_runs()
    runs.append({
        "id": run_id,
        "limit": limit,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    save_runs(runs)

    threading.Thread(target=execute_run, args=(run_id, limit), daemon=True).start()
    return jsonify({"ok": True, "id": run_id}), 201


@app.route("/api/runs/<run_id>/log", methods=["GET"])
def api_runs_log(run_id: str):
    log_path = RUNS_DIR / f"{run_id}.log"
    if not log_path.exists():
        return jsonify({"error": "Log introuvable"}), 404
    return jsonify({"log": log_path.read_text()})


if __name__ == "__main__":
    seed_roles_if_empty()
    prepare_ssh_key()
    app.run(host="0.0.0.0", port=5055)
