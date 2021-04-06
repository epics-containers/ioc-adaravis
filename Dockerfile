# EPICS SynApps Dockerfile
ARG REGISTRY=gcr.io/diamond-privreg/controls/prod
ARG ADCORE_VERSION=3.10b1

FROM epics-adcore
#FROM ${REGISTRY}/epics/epics-adcore:${ADCORE_VERSION}

ARG ARAVISGIGE_VERSION=R3-0

# install additional tools and libs
USER root

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libglib2.0-dev \
    intltool \
    pkg-config \
    xz-utils

# get additional support modules
USER ${USERNAME}

RUN ./add_module.sh areaDetector aravisGigE ARAVISGIGE ${ARAVISGIGE_VERSION}

# add CONFIG_SITE.linux and RELEASE.local
COPY --chown=1000 configure ${SUPPORT}/aravisGigE-${ARAVISGIGE_VERSION}/configure

# build vendor libraries
RUN aravisGigE-${ARAVISGIGE_VERSION}/install.sh

# update dependencies and build
RUN make release && \
    make -C aravisGigE-${ARAVISGIGE_VERSION} && \
    make -C aravisGigE-${ARAVISGIGE_VERSION} clean

# update the generic IOC Makefile
COPY --chown=1000 Makefile ${SUPPORT}/ioc/iocApp/src

# update dependencies and build (separate step for efficient image layers)
RUN make release && \
    make -C ioc && \
    make -C ioc clean
