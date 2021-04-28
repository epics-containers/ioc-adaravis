# EPICS SynApps Dockerfile
ARG REGISTRY=gcr.io/diamond-privreg/controls/prod
ARG ADCORE_VERSION=3.10b1.1

FROM ${REGISTRY}/epics/epics-adcore:${ADCORE_VERSION}

ARG ADARAVIS_VERSION=R2-2
ARG ADGENICAM_VERSION=R1-7

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

# get additional support modules
USER ${USERNAME}

RUN ./add_module.sh areaDetector ADGenICam ADGENICAM ${ADGENICAM_VERSION}
RUN ./add_module.sh areaDetector ADAravis ADARAVIS ${ADARAVIS_VERSION}

# add CONFIG_SITE.linux and RELEASE.local
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION}/configure
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADAravis-${ADARAVIS_VERSION}/configure

# update dependencies and build
RUN make release && \
    make -C ADGenICam-${ADGENICAM_VERSION} && \
    make -C ADGenICam-${ADGENICAM_VERSION} clean && \
    make -C ADAravis-${ADARAVIS_VERSION} && \
    make -C ADAravis-${ADARAVIS_VERSION} clean

# update the generic IOC Makefile
COPY --chown=${USER_UID}:${USER_GID} Makefile ${SUPPORT}/ioc/iocApp/src

# update dependencies and build (separate step for efficient image layers)
RUN make release && \
    make -C ioc && \
    make -C ioc clean
