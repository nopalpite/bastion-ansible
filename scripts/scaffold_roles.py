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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "inventory"))
import bastion_inventory

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"

ROLE_SKELETON = {
    "tasks/main.yml": "---\n# Taches pour le role {role}\n",
    "defaults/main.yml": "---\n",
    "meta/main.yml": '---\ngalaxy_info:\n  description: "Role Ansible pour la typologie \'{role}\'"\n',
}


def existing_roles() -> set[str]:
    if not ROLES_DIR.exists():
        return set()
    return {p.name for p in ROLES_DIR.iterdir() if p.is_dir()}


def scaffold(role: str) -> None:
    role_dir = ROLES_DIR / role
    for rel_path, template in ROLE_SKELETON.items():
        target = role_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(template.format(role=role))
    print(f"[+] role '{role}' cree sous {role_dir}")


def main() -> None:
    machines = bastion_inventory.fetch_machines()
    inventory = bastion_inventory.build_inventory(machines)
    tags = sorted(k for k in inventory if k != "_meta")

    existing = existing_roles()

    if "common" not in existing:
        scaffold("common")

    new_tags = [t for t in tags if t not in existing]
    if not new_tags:
        print("Aucun nouveau tag detecte - roles deja a jour.")
        return

    for tag in new_tags:
        scaffold(tag)


if __name__ == "__main__":
    main()
