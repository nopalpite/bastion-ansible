# bastion-ansible

Gestion du parc (push, Ansible) par-dessus l'inventaire deja maintenu
dans [Bastion](https://github.com/nopalpite/bastion) - voir la roadmap
complete pour le contexte et les decisions prises.

## Pourquoi un depot separe de Bastion

Bastion gere l'acces interactif a la demande (un humain, une session
SSH/VNC) ; ce depot gere des jobs de push en masse (potentiellement
longs). Les coupler ferait qu'un redeploiement de l'un percute l'autre,
pour aucun benefice. Bastion reste la **seule source de verite** sur
quelles machines existent - ce depot ne duplique jamais cette liste,
il interroge `GET /api/machines` a chaque run.

## Inventaire dynamique

`inventory/bastion_inventory.py` interroge l'API Bastion et groupe les
machines **par tag** (un groupe Ansible = un tag Bastion - une machine
avec plusieurs tags appartient a plusieurs groupes).

Variables d'environnement requises :

```bash
export BASTION_URL="https://bastion.example.com"
export BASTION_API_TOKEN="..."   # le meme configure cote Bastion (BASTION_API_TOKEN)
```

Verifier que l'inventaire se construit correctement :

```bash
ansible-inventory --list
```

## Authentification SSH du runner

Bastion n'expose **jamais** les identifiants via son API (choix de
securite assume). Ce depot n'authentifie donc pas ses connexions SSH via
Bastion : il utilise sa **propre cle dediee "automatisation"**, generee
a part et injectee dans `authorized_keys` a l'imaging/au provisioning
des machines - jamais via Bastion. Toute connexion via cette cle est par
construction un job Ansible, jamais une session humaine (utile pour
l'audit).

Cle generee (ed25519, sans passphrase - usage non-interactif dans des
jobs) : `secrets/automation_ed25519` (+ `.pub`). **Jamais commitee**
(tout `secrets/` est gitignore) - a sauvegarder ailleurs (gestionnaire
de secrets, coffre-fort) des maintenant, une cle perdue = a regenerer et
redistribuer partout.

A injecter dans `~/.ssh/authorized_keys` de chaque machine du parc a
l'imaging/provisioning (clef publique uniquement, ci-dessous) :

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKB+1TpyTG4tD2HYkwyK5F//9IinNcGr0lbqJ3am+HMc bastion-ansible-automation
```

Puis pointer Ansible dessus (`ansible.cfg` ou `-e ansible_ssh_private_key_file=...`) :

```ini
[defaults]
private_key_file = ./secrets/automation_ed25519
```

## Roles

Un role par typologie de machine (tag), plus un role `common` (mises a
jour de securite, agent de supervision...) applique a tout le parc en
amont des roles specifiques. Structure classique Ansible :
`roles/<typologie>/`.

Les roles suivent les tags **reels** presents dans Bastion plutot que
d'etre maintenus a la main en parallele (meme logique que l'inventaire :
une seule source de verite). `scripts/scaffold_roles.py` interroge
`GET /api/machines`, calcule les tags via la meme logique que
l'inventaire (`bastion_inventory.build_inventory`), et cree le squelette
(`tasks/`, `defaults/`, `meta/`) de tout role manquant - idempotent,
ne touche jamais un role deja present :

```bash
BASTION_URL=... BASTION_API_TOKEN=... ./scripts/scaffold_roles.py
```

## Playbook

`site.yml` relie inventaire et roles : `common` sur tout le parc, puis
un play par typologie (`hosts: <tag>`). Un nouveau tag scaffolde par
`scripts/scaffold_roles.py` doit etre ajoute a la main ici - les plays
Ansible ne peuvent pas boucler sur des groupes decouverts dynamiquement.

```bash
ansible-playbook site.yml               # tout le parc
ansible-playbook site.yml --limit gpio   # une seule typologie
ansible-playbook site.yml --check        # dry-run
```

**Windows** : `ansible-playbook` ne tourne pas nativement sur Windows
(limitation connue d'ansible-core, `os.get_blocking` non supporte) -
utiliser WSL, ou le conteneur ci-dessous qui contourne le probleme de
fait.

## Runner (conteneur)

Declenchement manuel pour l'instant (`docker compose run`, pas de
demon) - programmation (cron/scheduler) plus tard si le besoin se
confirme. Le depot est monte en volume (lecture seule), jamais copie a
l'image : editer un role/playbook prend effet immediatement, pas de
rebuild.

```bash
cp .env.example .env   # renseigner BASTION_URL/BASTION_API_TOKEN
docker compose run --rm runner                    # tout le parc
docker compose run --rm runner --limit gpio        # une seule typologie
docker compose run --rm runner --check             # dry-run
```

La cle privee (`secrets/automation_ed25519`) est copiee dans le
conteneur avec les bonnes permissions avant chaque run
(`entrypoint.sh`) - un bind mount depuis Windows/Docker Desktop expose
souvent les fichiers avec des permissions trop ouvertes, que ssh
refuserait telles quelles.

Image publiee sur GHCR a chaque push sur `main` et a chaque tag
`vX.Y.Z` (`.github/workflows/docker-build.yml`, meme structure que
celui de Bastion) - `linux/amd64` + `linux/arm64`.

## Etat actuel

- [x] Bastion expose `GET /api/machines`
- [x] Inventaire dynamique (`inventory/bastion_inventory.py`)
- [x] Cle SSH "automatisation" generee (distribution sur le parc encore a faire)
- [x] Outillage de scaffold des roles (`scripts/scaffold_roles.py`)
- [x] Premiers roles generes depuis Bastion : `common`, `desktop`, `gpio` (squelettes vides, taches a ecrire)
- [x] Playbook d'entree (`site.yml`) reliant inventaire et roles
- [x] Runner conteneurise, declenchement manuel (`docker compose run`)
- [x] Pipeline docker-build.yml (GHCR, multi-arch)
- [ ] Contenu reel des roles (taches) - a definir au fur et a mesure des tests de playbook
- [ ] Programmation du runner (cron/scheduler) - si le besoin se confirme
