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
import shlex
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
import render_site_yml  # noqa: E402
import scaffold_roles  # noqa: E402

app = Flask(__name__)

ROLES_DIR = REPO_ROOT / "roles"
ROLES_SEED_DIR = Path("/opt/roles-seed")
ORDER_PATH = REPO_ROOT / "order.yaml"
ORDER_SEED_PATH = Path("/opt/order-seed.yaml")
SITE_YML = REPO_ROOT / "site.yml"
SITE_SEED_PATH = Path("/opt/site-seed.yml")
RUNS_DIR = REPO_ROOT / "runs"
RUNS_INDEX = RUNS_DIR / "index.yaml"
SSH_KEY_SRC = REPO_ROOT / "secrets" / "automation_ed25519"
SSH_KEY_RUN = Path("/tmp/automation_ed25519")

TAG_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,64}$")
YAML_EXTENSIONS = (".yml", ".yaml")

RUN_STATE = {"running": False}
RUN_LOCK = threading.Lock()


def seed_state_if_empty() -> None:
    """Premiere execution sans checkout local (ex: expolab, roles/ monte
    vide) : copie les references bakees a la construction de l'image
    (roles/, order.yaml, site.yml). Ne touche jamais un fichier/dossier
    deja peuple (checkout local en dev, ou un second demarrage dans un
    environnement deja seed)."""
    if (not ROLES_DIR.exists() or not any(ROLES_DIR.iterdir())) and ROLES_SEED_DIR.exists():
        ROLES_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROLES_SEED_DIR, ROLES_DIR, dirs_exist_ok=True)

    # .stat().st_size == 0 (pas juste "absent") : un deploiement peut
    # avoir pre-cree ces fichiers vides via `touch` pour que le bind
    # mount d'un FICHIER (pas un dossier) ne se transforme pas en dossier
    # vide au demarrage (voir server/deploy-server.sh dans expolab).
    if (not ORDER_PATH.exists() or ORDER_PATH.stat().st_size == 0) and ORDER_SEED_PATH.exists():
        shutil.copy(ORDER_SEED_PATH, ORDER_PATH)

    if (not SITE_YML.exists() or SITE_YML.stat().st_size == 0) and SITE_SEED_PATH.exists():
        shutil.copy(SITE_SEED_PATH, SITE_YML)


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


def list_role_files(role: str) -> list[str]:
    base = ROLES_DIR / role
    if not base.exists():
        return []
    return sorted(
        str(p.relative_to(base)).replace(os.sep, "/")
        for p in base.rglob("*")
        if p.is_file()
    )


def resolve_role_file(role: str, relpath: str) -> Path | None:
    """Resout un chemin relatif a l'interieur d'un role, en verifiant
    qu'il n'en sort jamais (pas de traversal via ../ ou chemin absolu) -
    seule protection restante maintenant que n'importe quel fichier du
    role est editable, pas juste 3 chemins fixes codes en dur."""
    if role not in local_roles() or not relpath:
        return None
    base = (ROLES_DIR / role).resolve()
    target = (base / relpath).resolve()
    if target != base and base not in target.parents:
        return None
    return target


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
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNS_DIR / f"{run_id}.log"
    cmd = ["ansible-playbook", str(SITE_YML)]
    if limit:
        cmd += ["--limit", limit]
    # Args supplementaires fixes pour tout run declenche par l'UI (ex:
    # --extra-vars ansible_become_pass=... pour un environnement de demo
    # ou le mot de passe sudo est connu/partage) - jamais une valeur par
    # defaut de ce depot, uniquement ce qu'un deploiement fournit via son
    # propre environnement (voir server/stacks/bastion-ansible dans
    # expolab pour un exemple d'utilisation).
    extra_args = os.environ.get("BASTION_ANSIBLE_EXTRA_ARGS", "")
    if extra_args:
        cmd += shlex.split(extra_args)
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
    return jsonify({"files": list_role_files(role)})


@app.route("/api/roles/<role>/file/<path:relpath>", methods=["GET"])
def api_role_file_get(role: str, relpath: str):
    target = resolve_role_file(role, relpath)
    if target is None or not target.is_file():
        return jsonify({"error": "Fichier introuvable"}), 404
    return jsonify({"content": target.read_text()})


@app.route("/api/roles/<role>/file/<path:relpath>", methods=["PUT"])
def api_role_file_put(role: str, relpath: str):
    target = resolve_role_file(role, relpath)
    if target is None:
        return jsonify({"error": "Chemin invalide (doit rester a l'interieur du role)"}), 400

    body = request.get_json(force=True, silent=True) or {}
    content = body.get("content", "")

    if target.suffix in YAML_EXTENSIONS:
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return jsonify({"error": f"YAML invalide : {exc}"}), 400

    # Ecriture atomique (tmp+rename) : sur dans ce cas, contrairement a
    # order.yaml/site.yml (voir README) - roles/ est toujours monte comme
    # un DOSSIER (jamais un fichier individuel), remplacer un fichier a
    # l'interieur n'est jamais bloque par un mount Docker.
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, target)
    return jsonify({"ok": True})


@app.route("/api/roles/<role>/file/<path:relpath>", methods=["DELETE"])
def api_role_file_delete(role: str, relpath: str):
    target = resolve_role_file(role, relpath)
    if target is None or not target.is_file():
        return jsonify({"error": "Fichier introuvable"}), 404
    target.unlink()
    return jsonify({"ok": True})


@app.route("/api/order", methods=["GET"])
def api_order_get():
    return jsonify({"order": scaffold_roles.load_order()})


@app.route("/api/order", methods=["PUT"])
def api_order_put():
    body = request.get_json(force=True, silent=True) or {}
    order = body.get("order")
    if not isinstance(order, list) or set(order) != local_roles():
        return jsonify({"error": "L'ordre doit contenir exactement les roles existants, sans doublon ni omission."}), 400

    scaffold_roles.save_order(order)
    render_site_yml.render_to_file(order, SITE_YML)
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
    seed_state_if_empty()
    prepare_ssh_key()
    app.run(host="0.0.0.0", port=5055)
