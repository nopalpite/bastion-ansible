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

Un role par typologie de machine (tag), strictement lie a son groupe
(`hosts: <tag>`) - aucun role "commun" applique inconditionnellement a
tout le parc (retire volontairement : pas de tag Bastion ne le
justifiait). Structure classique Ansible : `roles/<typologie>/`.

Les roles suivent les tags **reels** presents dans Bastion plutot que
d'etre maintenus a la main en parallele (meme logique que l'inventaire :
une seule source de verite). `scripts/scaffold_roles.py` interroge
`GET /api/machines`, calcule les tags via la meme logique que
l'inventaire (`bastion_inventory.build_inventory`), cree le squelette
(`tasks/`, `defaults/`, `meta/`) de tout role manquant - idempotent,
ne touche jamais un role deja present - et l'**ajoute automatiquement**
a la fin de `order.yaml` (voir ci-dessous) :

```bash
BASTION_URL=... BASTION_API_TOKEN=... ./scripts/scaffold_roles.py
```

## Ordre d'execution (`order.yaml`) et `site.yml`

Une machine avec plusieurs tags recoit chaque role dans l'ordre defini
par `order.yaml` (**empilable** - ex: `display` avant `gpio` pour
installer l'environnement graphique avant une stack qui en depend) :

```yaml
order:
  - display
  - gpio
```

`site.yml` est **genere** depuis `order.yaml` par
`scripts/render_site_yml.py` (meme principe que
`server/render-caddyfile.py` dans expolab : `services.yaml` ->
`Caddyfile`) - jamais edite a la main pour la partie plays, ecrase au
prochain scaffold/reordonnancement :

```bash
./scripts/render_site_yml.py   # regenere site.yml depuis order.yaml
```

`order.yaml` reste git-tracked (comme `site.yml`, qui continue de
fonctionner des un checkout frais sans etape de generation
prealable). Le webui (page "Ordre d'execution") permet de reordonner
sans toucher a aucun fichier a la main - regenere `site.yml`
automatiquement a chaque changement.

**Piege bind mount Docker** : `save_order()`/`render_to_file()` ecrivent
directement dans le fichier existant (jamais de tmp+rename/`os.replace`)
- si `order.yaml`/`site.yml` sont montes individuellement comme des
fichiers (cas d'expolab, contrairement a `roles/`, monte comme un
dossier), remplacer l'inode cible echoue avec `EBUSY` ("Device or
resource busy"), le mount ne pouvant pas etre substitue. Deja rencontre
en pratique : `scaffold()` creait le role mais plantait avant de mettre
a jour `order.yaml`, desynchronisant les deux.

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
confirme.

L'image publiee **integre deja** `site.yml`/`roles/`/`inventory/`/`scripts/`
(copies par le Dockerfile) - elle est utilisable seule, sans checkout de
ce depot (cas d'un deploiement qui consomme juste l'image, ex: expolab).
En local, `docker-compose.yml` monte quand meme le depot par-dessus
(bind mount, prioritaire sur le contenu de l'image) : editer un
role/playbook prend effet immediatement, pas de rebuild - les deux
usages cohabitent sans rien reconfigurer.

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

## Interface web (`webui/`)

Service supplementaire a cote du runner CLI ci-dessus - pas un
remplacement, un conteneur en plus dans le meme `docker-compose.yml`
(memes dependances : ansible-core, execute `ansible-playbook` lui-meme
en subprocess). Permet, sans repasser par le CLI/SSH a chaque fois :

- **Roles** : liste des roles locaux, editeur texte brut pour **n'importe
  quel fichier du role** (pas seulement `tasks/main.yml` - `handlers/`,
  `templates/*.j2`, `vars/`, etc.), creation/suppression de fichier
  depuis l'UI (chemin relatif libre), validation YAML avant sauvegarde
  pour les fichiers `.yml`/`.yaml` uniquement (un `.j2` n'est pas du
  YAML, pas de validation forcee dessus).
- **Tags sans role** : detecte les tags Bastion sans role correspondant
  (meme calcul que `scripts/scaffold_roles.py`), bouton "Scaffolder"
  pour creer le squelette depuis l'UI.
- **Ordre d'execution** : reordonne `order.yaml` (boutons monter/descendre
  par role), regenere `site.yml` automatiquement a chaque changement.
- **Runs** : declenche `site.yml` (tout le parc ou `--limit <tag>`),
  historique avec statut et logs (`runs/index.yaml` + un fichier de log
  par run, non versionnes).

```bash
docker compose up webui   # http://localhost:5055
```

`BASTION_ANSIBLE_EXTRA_ARGS` (optionnelle) : arguments supplementaires
ajoutes a chaque run declenche par l'UI (ex: `--extra-vars
ansible_become_pass=...` pour un environnement de demo au mot de passe
sudo connu/partage) - jamais de valeur par defaut dans ce depot,
uniquement ce qu'un deploiement fournit via son propre environnement.

En local, le depot est monte en **lecture-ecriture** (contrairement au
`:ro` du runner) : editer un role via l'UI edite directement les
fichiers du checkout git. Dans un environnement sans checkout (ex:
expolab, qui consomme juste l'image publiee), `roles/` est seede une
seule fois depuis une copie de reference bakee dans l'image
(`/opt/roles-seed`, jamais touchee si `roles/` contient deja quelque
chose).

**Pas d'authentification** sur cette UI (comme les autres apps admin
inspirees par ce depot) - elle peut executer des taches `become: true`
contre tout le parc reference dans Bastion. A ne jamais exposer au-dela
d'un reseau de confiance sans ajouter au moins une authentification
basique devant.

## Etat actuel

- [x] Bastion expose `GET /api/machines`
- [x] Inventaire dynamique (`inventory/bastion_inventory.py`)
- [x] Cle SSH "automatisation" generee (distribution sur le parc encore a faire)
- [x] Outillage de scaffold des roles (`scripts/scaffold_roles.py`)
- [x] Premiers roles generes depuis Bastion : `desktop`, `gpio` (squelettes vides, taches a ecrire)
- [x] Playbook d'entree (`site.yml`) reliant inventaire et roles
- [x] Runner conteneurise, declenchement manuel (`docker compose run`)
- [x] Pipeline docker-build.yml (GHCR, multi-arch)
- [x] Valide de bout en bout dans expolab (inventaire, auth, become, execution reussis contre un faux Pi)
- [x] Interface web (`webui/`) : roles, declenchement de runs, historique
- [x] Ordre d'execution configurable (`order.yaml` -> `site.yml` genere), editable depuis l'UI
- [ ] Contenu reel des roles (taches) - a definir au fur et a mesure des tests de playbook
- [ ] Programmation du runner (cron/scheduler) - si le besoin se confirme
