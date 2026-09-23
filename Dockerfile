# Image du runner Ansible - execute site.yml contre le parc.
#
# Le contenu (site.yml, roles/, inventory/, scripts/, ansible.cfg) est
# COPIE dans l'image : necessaire pour qu'une image publiee (GHCR) soit
# utilisable seule, sans avoir a cloner ce depot a cote (ex: deploiement
# expolab, qui consomme l'image sans checkout du code source). En
# developpement local, docker-compose.yml monte quand meme le depot par
# dessus (bind mount, prioritaire sur le contenu de l'image) : editer un
# role/playbook prend toujours effet immediatement sans rebuild - les
# deux usages cohabitent sans configuration differente.
#
# Existe aussi pour contourner une limitation reelle : ansible-core ne
# tourne pas nativement sur Windows (os.get_blocking non supporte) - ce
# conteneur est le moyen le plus simple de lancer site.yml depuis le
# poste de dev, pas seulement une histoire de reseau/VPN vers Bastion.
FROM python:3.12-slim

RUN apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-client git && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir ansible-core==2.17.* flask==3.0.* pyyaml==6.0.*

WORKDIR /repo
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY site.yml order.yaml ansible.cfg ./
COPY roles/ roles/
COPY inventory/ inventory/
COPY scripts/ scripts/
COPY webui/ webui/
# Copies de reference pour le seed initial (roles/, order.yaml, site.yml)
# dans un environnement sans checkout local (ex: expolab) - voir
# webui/app.py:seed_state_if_empty. Jamais utilisees si le fichier/dossier
# monte est deja peuple (bind mount local, ou deja seed precedemment).
COPY roles/ /opt/roles-seed/
COPY order.yaml /opt/order-seed.yaml
COPY site.yml /opt/site-seed.yml

ENTRYPOINT ["/entrypoint.sh"]
