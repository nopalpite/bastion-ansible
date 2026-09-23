#!/usr/bin/env python3
"""Inventaire Ansible dynamique base sur l'API Bastion (GET /api/machines).

Groupe les machines par tag (un groupe Ansible = un tag Bastion - une
machine avec plusieurs tags appartient a plusieurs groupes, ce qui colle
au cas de plusieurs typologies de machines dans le parc). Bastion
n'expose jamais les identifiants via cette API (choix de securite
assume cote Bastion) : l'authentification SSH du runner passe par une
cle dediee "automatisation", pas par Bastion (voir README.md, Phase 3
de la roadmap).

Usage (format standard d'un inventory script Ansible) :
    ./bastion_inventory.py --list
    ./bastion_inventory.py --host <name>

Variables d'environnement requises :
    BASTION_URL        ex: https://bastion.example.com
    BASTION_API_TOKEN  jeton configure cote Bastion (env BASTION_API_TOKEN)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASTION_URL = os.environ.get("BASTION_URL", "").rstrip("/")
BASTION_API_TOKEN = os.environ.get("BASTION_API_TOKEN", "")

GROUP_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def fail(message: str) -> None:
    print(f"bastion_inventory: {message}", file=sys.stderr)
    sys.exit(1)


def fetch_machines() -> list[dict]:
    if not BASTION_URL:
        fail("BASTION_URL non definie")
    if not BASTION_API_TOKEN:
        fail("BASTION_API_TOKEN non definie")

    req = urllib.request.Request(
        f"{BASTION_URL}/api/machines",
        headers={"Authorization": f"Bearer {BASTION_API_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        fail(f"API Bastion a repondu {exc.code} - endpoint desactive (BASTION_API_TOKEN non configure cote Bastion) ou token invalide ?")
    except urllib.error.URLError as exc:
        fail(f"Impossible de joindre {BASTION_URL} : {exc.reason}")


def group_name(tag: str) -> str:
    # Un nom de groupe Ansible ne doit contenir que [A-Za-z0-9_] - les
    # tags Bastion (catalogue gere cote Bastion, mais pas garanti
    # compatible tel quel) sont normalises plutot que de faire planter
    # l'inventaire sur un tag avec un espace ou un tiret.
    return GROUP_NAME_RE.sub("_", tag).strip("_") or "sans_tag"


def build_inventory(machines: list[dict]) -> dict:
    inventory: dict = {"_meta": {"hostvars": {}}}
    groups: dict[str, list[str]] = {}

    for m in machines:
        name = m["name"]
        hostvars = {"ansible_host": m["host"], "bastion_id": m["id"]}
        if m.get("ssh_port"):
            hostvars["ansible_port"] = m["ssh_port"]
        if m.get("os"):
            hostvars["bastion_os"] = m["os"]
        if m.get("site"):
            hostvars["bastion_site"] = m["site"]
        inventory["_meta"]["hostvars"][name] = hostvars

        for tag in (m.get("tags") or []):
            groups.setdefault(group_name(tag), []).append(name)

    for group, hosts in groups.items():
        inventory[group] = {"hosts": hosts}

    return inventory


def main() -> None:
    if "--list" in sys.argv:
        machines = fetch_machines()
        print(json.dumps(build_inventory(machines)))
    elif "--host" in sys.argv:
        # Toutes les hostvars sont deja fournies via _meta dans --list -
        # Ansible n'appelle --host que si _meta en est absent. Supporte
        # quand meme un appel manuel, sans dupliquer une requete API.
        print(json.dumps({}))
    else:
        fail("usage: --list | --host <name>")


if __name__ == "__main__":
    main()
