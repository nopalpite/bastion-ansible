#!/usr/bin/env python3
"""Genere site.yml a partir de order.yaml (source de verite de la
sequence d'execution) - meme principe que server/render-caddyfile.py
dans expolab (services.yaml -> Caddyfile) : order.yaml est edite (a la
main ou via le webui), site.yml est l'artefact regenere, jamais edite a
la main pour la partie plays.

Usage: ./scripts/render_site_yml.py [order.yaml] [site.yml]
"""
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ORDER_PATH = REPO_ROOT / "order.yaml"
DEFAULT_SITE_PATH = REPO_ROOT / "site.yml"

PLAY_NAMES = {
    "common": "Base commune a tout le parc",
}

HEADER = (
    "# GENERE par scripts/render_site_yml.py a partir de order.yaml - ne pas\n"
    "# editer les plays ci-dessous a la main, elles seraient ecrasees au\n"
    "# prochain scaffold/reordonnancement. order.yaml est la source de verite\n"
    "# de la sequence d'execution.\n"
    "#\n"
    "# Usage :\n"
    "#   ansible-playbook site.yml               # tout le parc\n"
    "#   ansible-playbook site.yml --limit gpio   # une seule typologie\n"
    "#   ansible-playbook site.yml --check        # dry-run\n"
)


def load_order(path: Path = DEFAULT_ORDER_PATH) -> list[str]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("order", [])


def render(order: list[str]) -> str:
    plays = []
    for role in order:
        hosts = "all" if role == "common" else role
        plays.append({
            "name": PLAY_NAMES.get(role, f"Typologie {role}"),
            "hosts": hosts,
            "become": True,
            "roles": [role],
        })
    body = yaml.safe_dump(plays, sort_keys=False, default_flow_style=False)
    return f"---\n{HEADER}\n{body}"


def render_to_file(order: list[str], site_path: Path = DEFAULT_SITE_PATH) -> None:
    # Ecriture atomique - meme precaution que partout ailleurs dans ce
    # depot (evite un site.yml tronque si le process est interrompu).
    tmp_path = site_path.with_suffix(".tmp")
    tmp_path.write_text(render(order))
    os.replace(tmp_path, site_path)


def main() -> None:
    order_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ORDER_PATH
    site_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SITE_PATH
    render_to_file(load_order(order_path), site_path)


if __name__ == "__main__":
    main()
