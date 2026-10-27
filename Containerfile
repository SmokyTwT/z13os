# Smoky OS — image système (Fedora Silverblue atomique) pour ROG Flow Z13 GZ301ZE
ARG FEDORA_VERSION=44
FROM quay.io/fedora/fedora-silverblue:${FEDORA_VERSION}

# Adresse Moodle (variable de dépôt GitHub MOODLE_URL) et nom affiché de la distrib
ARG MOODLE_URL="https://moodle.uphf.fr/"
ARG DISTRO_NAME="Smoky OS"
# 1 = variante avec le pilote NVIDIA propriétaire (image z13os-nvidia)
ARG NVIDIA=0

COPY system_files/ /
COPY build_files/build.sh /tmp/build.sh

RUN MOODLE_URL="${MOODLE_URL}" DISTRO_NAME="${DISTRO_NAME}" NVIDIA="${NVIDIA}" bash /tmp/build.sh && \
    ostree container commit
