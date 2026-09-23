# bastion-ansible

Gestion du parc (push, Ansible) par-dessus l'inventaire deja maintenu
dans [Bastion](https://github.com/nopalpite/bastion) - voir la roadmap
complete pour le contexte et les decisions prises.

Depot Ansible classique : inventaire dynamique + roles + un script pour
generer le playbook d'entree. Pas d'image Docker, pas d'UI - l'edition
passe par git/votre editeur, le declenchement/historique par
[Semaphore UI](#executeur--semaphore-ui) (voir plus bas).

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
avec plusieurs tags appartient a plusieurs groupes). Executable (`+x`) :
Ansible le traite nativement comme un inventaire dynamique des qu'on le
passe en `-i` - aucune configuration Semaphore-specifique necessaire au
dela de pointer l'Inventory dessus (voir plus bas).

Variables d'environnement requises :

```bash
export BASTION_URL="https://bastion.example.com"
export BASTION_API_TOKEN="..."   # le meme configure cote Bastion (BASTION_API_TOKEN)
```

Verifier que l'inventaire se construit correctement :

```bash
ansible-inventory --list
```

## Authentification SSH (cle "automatisation")

Bastion n'expose **jamais** les identifiants via son API (choix de
securite assume). Ce depot n'authentifie donc jamais ses connexions SSH
via Bastion : une **cle dediee "automatisation"**, generee a part et
injectee dans `authorized_keys` a l'imaging/au provisioning des
machines - jamais via Bastion. Toute connexion via cette cle est par
construction un job Ansible, jamais une session humaine (utile pour
l'audit).

Cle generee (ed25519, sans passphrase - usage non-interactif dans des
jobs) : `secrets/automation_ed25519` (+ `.pub`). **Jamais commitee**
(tout `secrets/` est gitignore) - a importer dans le Key Store de
Semaphore (voir plus bas), et a sauvegarder ailleurs (gestionnaire de
secrets, coffre-fort), une cle perdue = a regenerer et redistribuer
partout.

A injecter dans `~/.ssh/authorized_keys` de chaque machine du parc a
l'imaging/provisioning (clef publique uniquement).

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
fonctionner des un checkout frais sans etape de generation prealable).
Reordonner = editer `order.yaml` a la main puis regenerer, `git commit`,
`git push` - comme n'importe quel autre changement de ce depot.

```bash
ansible-playbook site.yml               # tout le parc
ansible-playbook site.yml --limit gpio   # une seule typologie
ansible-playbook site.yml --check        # dry-run
```

**Windows** : `ansible-playbook` ne tourne pas nativement sur Windows
(limitation connue d'ansible-core, `os.get_blocking` non supporte) -
utiliser WSL, ou laisser Semaphore executer (conteneur Linux).

## Executeur : Semaphore UI

Le declenchement (manuel/programme) et l'historique des runs passent
par [Semaphore UI](https://semaphoreui.com) (auto-heberge, projet
separe) plutot que par un outil maison - AWX ecarte comme trop lourd
pour un parc de cette taille, Semaphore est le bon calibre (un seul
binaire/image Docker, SQLite, pas de Postgres/Redis a operer).

Semaphore clone ce depot lui-meme a chaque run (pas d'image Docker a
publier depuis ce depot). Pointe sur le mirroir git local du lab
(`git-mirror`), pas directement sur GitHub - sync manuel sur le mirroir
avant chaque campagne de deploiement.

Configuration initiale (etape manuelle unique dans l'UI Semaphore, comme
la configuration de l'environnement Dockhand dans expolab) :

1. **Repository** -> URL du mirroir `git-mirror` (branche `main`,
   Access Key = None si le mirroir n'est pas prive).
2. **Key Store** -> importer `secrets/automation_ed25519` (SSH,
   utilisateur cible selon la machine - `pi` dans le lab expolab).
3. **Inventory** -> type `file`, chemin `inventory/bastion_inventory.py`,
   credential = la cle SSH ci-dessus.
4. **Variable Group** -> `BASTION_URL`, `BASTION_API_TOKEN` (memes
   valeurs que cote Bastion), plus toute variable specifique a
   l'environnement (ex: `ANSIBLE_HOST_KEY_CHECKING=false` dans le lab,
   ou faux Pi recrees souvent).
5. **Task Template** -> playbook `site.yml`, extra vars si besoin (ex:
   `ansible_become_pass=...` pour un environnement ou le mot de passe
   sudo est connu/partage).
6. Lancer une fois depuis l'UI pour valider, puis eventuellement une
   **Schedule** (cron) pour de l'execution programmee.

L'API Semaphore (`Authorization: Bearer <token>`,
`POST /api/project/{id}/tasks {"template_id": N}`) permet de declencher
une tache par programme - pas branche automatiquement sur le sync du
mirroir pour l'instant (sync manuel assume), possible amelioration
future.

## Etat actuel

- [x] Bastion expose `GET /api/machines`
- [x] Inventaire dynamique (`inventory/bastion_inventory.py`)
- [x] Cle SSH "automatisation" generee (distribution sur le parc encore a faire)
- [x] Outillage de scaffold des roles (`scripts/scaffold_roles.py`)
- [x] Premiers roles generes depuis Bastion : `desktop`, `gpio` (squelettes vides, taches a ecrire)
- [x] Playbook d'entree (`site.yml`) reliant inventaire et roles, ordre configurable (`order.yaml`)
- [x] Valide de bout en bout dans expolab (inventaire, auth, become, execution reussis contre un faux Pi)
- [x] Executeur Semaphore UI (deploiement + configuration cote expolab)
- [ ] Contenu reel des roles (taches) - a definir au fur et a mesure des tests de playbook
- [ ] Brancher l'API Semaphore sur un sync reussi du mirroir (optionnel)
