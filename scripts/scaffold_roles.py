#!/usr/bin/env python3
"""Cree un squelette de role Ansible pour chaque tag Bastion inconnu.

Interroge la meme API que l'inventaire dynamique (voir
inventory/bastion_inventory.py) pour rester sur l'unique source de
verite du parc - les roles suivent les tags reels tels qu'ils
apparaissent dans Bastion plutot que d'etre maintenus a la main en
parallele et de finir par diverger.

Idempotent : ne touche jamais un role deja present (ni ses fichiers
existants), se contente d'ajouter ce qui manque.

Usage:
    BASTION_URL=... BASTION_API_TOKEN=... ./scripts/scaffold_roles.py
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "inventory"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bastion_inventory
import render_site_yml

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
ORDER_PATH = Path(__file__).resolve().parent.parent / "order.yaml"
SITE_PATH = Path(__file__).resolve().parent.parent / "site.yml"

ROLE_SKELETON = {
    "tasks/main.yml": "---\n# Taches pour le role {role}\n",
    "defaults/main.yml": "---\n",
    "meta/main.yml": '---\ngalaxy_info:\n  description: "Role Ansible pour la typologie \'{role}\'"\n',
}


def existing_roles() -> set[str]:
    if not ROLES_DIR.exists():
        return set()
    return {p.name for p in ROLES_DIR.iterdir() if p.is_dir()}


def load_order() -> list[str]:
    if not ORDER_PATH.exists():
        return []
    data = yaml.safe_load(ORDER_PATH.read_text()) or {}
    return data.get("order", [])


def save_order(order: list[str]) -> None:
    # Ecriture directe (pas de tmp+rename) : order.yaml peut etre un bind
    # mount Docker sur un seul fichier (ex: expolab) - y remplacer
    # l'inode cible via os.replace() echoue avec EBUSY ("Device or
    # resource busy"), le mount ne pouvant pas etre substitue. Ecrire
    # dans le fichier existant fonctionne dans tous les cas (mount de
    # fichier, mount de dossier, ou checkout local).
    ORDER_PATH.write_text(yaml.safe_dump({"order": order}, sort_keys=False))


def scaffold(role: str) -> None:
    role_dir = ROLES_DIR / role
    for rel_path, template in ROLE_SKELETON.items():
        target = role_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(template.format(role=role))
    print(f"[+] role '{role}' cree sous {role_dir}")

    # Ajoute a la fin de la sequence d'execution si absent, et regenere
    # site.yml en consequence - order.yaml reste la seule source de
    # verite de l'ordre, jamais site.yml edite a la main.
    order = load_order()
    if role not in order:
        order.append(role)
        save_order(order)
    render_site_yml.render_to_file(order, SITE_PATH)


def main() -> None:
    machines = bastion_inventory.fetch_machines()
    inventory = bastion_inventory.build_inventory(machines)
    tags = sorted(k for k in inventory if k != "_meta")

    existing = existing_roles()

    new_tags = [t for t in tags if t not in existing]
    if not new_tags:
        print("Aucun nouveau tag detecte - roles deja a jour.")
        return

    for tag in new_tags:
        scaffold(tag)


if __name__ == "__main__":
    main()
