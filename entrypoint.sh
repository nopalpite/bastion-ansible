#!/usr/bin/env bash
# Le depot est monte en lecture seule (docker-compose.yml) et, depuis un
# hote Windows/Docker Desktop, un bind mount expose souvent les fichiers
# avec des permissions trop ouvertes - ssh refuse alors la cle privee
# ("UNPROTECTED PRIVATE KEY FILE"). On en fait une copie a permissions
# correctes dans le conteneur avant chaque run, jamais reutilisee entre
# containers (ephemere, /tmp).
set -euo pipefail

KEY_SRC="/repo/secrets/automation_ed25519"
KEY_RUN="/tmp/automation_ed25519"

if [ -f "$KEY_SRC" ]; then
    cp "$KEY_SRC" "$KEY_RUN"
    chmod 600 "$KEY_RUN"
    export ANSIBLE_PRIVATE_KEY_FILE="$KEY_RUN"
fi

cd /repo
exec ansible-playbook site.yml "$@"
