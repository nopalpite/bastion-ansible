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

## Roles

Un role par typologie de machine (tag), plus un role `common` (mises a
jour de securite, agent de supervision...) applique a tout le parc en
amont des roles specifiques. Structure classique Ansible :
`roles/<typologie>/`.

## Etat actuel

- [x] Bastion expose `GET /api/machines`
- [x] Inventaire dynamique (`inventory/bastion_inventory.py`)
- [ ] Cle SSH "automatisation" generee et distribuee
- [ ] Premiers roles (`common` + au moins une typologie)
- [ ] Execution du runner (conteneur, declenchement manuel puis programme)
