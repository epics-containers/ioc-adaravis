# EPICS SynApps Dockerfile
ARG REGISTRY=ghcr.io/epics-containers
ARG ADCORE_VERSION=3.10r1.0

FROM ${REGISTRY}/epics-adcore:${ADCORE_VERSION}

ARG ADARAVIS_VERSION=R2-2-1
ARG ADGENICAM_VERSION=R1-8

# install additional tools and libs
USER root

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libglib2.0-dev \
    meson \
    intltool \
    pkg-config \
    xz-utils

# build aravis library
RUN cd /usr/local && \
    git clone https://github.com/AravisProject/aravis && \
    cd aravis && \
    git checkout ARAVIS_0_8_1 && \
    meson build && \
    cd build && \
    ninja && \
    ninja install && \
    echo /usr/local/lib64 > /etc/ld.so.conf.d/usr.conf && \
    ldconfig

USER ${USERNAME}

# get additional support modules
RUN python3 module.py add areaDetector ADGenICam ADGENICAM ${ADGENICAM_VERSION}
RUN python3 module.py add areaDetector ADAravis ADARAVIS ${ADARAVIS_VERSION}

# add CONFIG_SITE.linux and RELEASE.local
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION}/configure
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADAravis-${ADARAVIS_VERSION}/configure

# update the generic IOC Makefile to include the new support
COPY --chown=${USER_UID}:${USER_GID} Makefile ${SUPPORT}/ioc/iocApp/src

# update dependencies and build the support modules and the ioc
RUN python3 module.py dependencies && \
    make && \
    make  clean

