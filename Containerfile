# Smoky OS — image système (Fedora Silverblue atomique) pour ROG Flow Z13 GZ301ZE
#
# Image finale = socle (Containerfile.socle : Fedora, paquets, thèmes tiers, démarrage)
#              + fichiers Smoky (system_files/) + réglages (build_files/smoky.sh).
# Rien n'est téléchargé ici : cette partie se reconstruit en une minute et pèse quelques Mo.
#
# En local :  podman build -f Containerfile.socle -t smoky-socle .
#             podman build --build-arg SOCLE=smoky-socle -t smokyos .
ARG SOCLE=ghcr.io/smokytwt/z13os:socle
FROM ${SOCLE}

# Adresse Moodle (variable de dépôt GitHub MOODLE_URL) et nom affiché de la distrib
ARG MOODLE_URL="https://moodle.uphf.fr/"
ARG DISTRO_NAME="Smoky OS"

COPY system_files/ /
COPY build_files/smoky.sh /tmp/smoky.sh

RUN MOODLE_URL="${MOODLE_URL}" DISTRO_NAME="${DISTRO_NAME}" bash /tmp/smoky.sh && \
    ostree container commit
