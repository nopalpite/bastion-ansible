# Image du runner Ansible - execute site.yml contre le parc. Le depot
# est monte en volume (docker-compose.yml), jamais copie a l'image :
# editer un role/playbook prend effet immediatement, pas de rebuild.
#
# Existe aussi pour contourner une limitation reelle : ansible-core ne
# tourne pas nativement sur Windows (os.get_blocking non supporte) - ce
# conteneur est le moyen le plus simple de lancer site.yml depuis le
# poste de dev, pas seulement une histoire de reseau/VPN vers Bastion.
FROM python:3.12-slim

RUN apt-get update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-client git && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir ansible-core==2.17.*

WORKDIR /repo
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
