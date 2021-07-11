# Add support for GigE cameras with the ADAravis support module
ARG REGISTRY=ghcr.io/epics-containers
ARG ADCORE_VERSION=3.10r3.0

ARG ADARAVIS_VERSION=R2-2-1
ARG ADGENICAM_VERSION=R1-8

##### build stage ##############################################################

FROM ${REGISTRY}/epics-areadetector:${ADCORE_VERSION} AS developer

ARG ADARAVIS_VERSION
ARG ADGENICAM_VERSION

# install additional packages
USER root

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libglib2.0-dev \
    meson \
    intltool \
    pkg-config \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# build aravis library
RUN cd /usr/local && \
    git clone -b ARAVIS_0_8_1 --depth 1 https://github.com/AravisProject/aravis && \
    cd aravis && \
    meson build && \
    cd build && \
    ninja && \
    ninja install && \
    rm -fr /usr/local/aravis

USER ${USERNAME}

# get additional support modules
RUN python3 module.py add areaDetector ADGenICam ADGENICAM ${ADGENICAM_VERSION}
RUN python3 module.py add areaDetector ADAravis ADARAVIS ${ADARAVIS_VERSION}

# add CONFIG_SITE.linux and RELEASE.local
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION}/configure
COPY --chown=${USER_UID}:${USER_GID} configure ${SUPPORT}/ADAravis-${ADARAVIS_VERSION}/configure

# update the generic IOC Makefile to include the new support
COPY --chown=${USER_UID}:${USER_GID} Makefile ${IOC}/iocApp/src

# update dependencies and build the support modules and the ioc
RUN python3 module.py dependencies
RUN make -j -C  ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION} && \
    make -j -C  ${SUPPORT}/ADAravis-${ADARAVIS_VERSION} && \
    make -j -C  ${IOC} && \
    make -j clean

##### runtime stage ############################################################

FROM ${REGISTRY}/epics-areadetector:${ADCORE_VERSION}.run AS runtime

ARG ADARAVIS_VERSION
ARG ADGENICAM_VERSION

# install runtime libraries from additional packages section above
USER root

RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libglib2.0-bin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=developer /usr/local/lib/x86_64-linux-gnu/libaravis* /usr/local/lib/x86_64-linux-gnu/
ENV LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/usr/local/lib/x86_64-linux-gnu/

USER ${USERNAME}

# get the products from the build stage
COPY --from=developer ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION} ${SUPPORT}/ADGenICam-${ADGENICAM_VERSION}
COPY --from=developer ${SUPPORT}/ADAravis-${ADARAVIS_VERSION} ${SUPPORT}/ADAravis-${ADARAVIS_VERSION}
COPY --from=developer --chown=${USER_UID}:${USER_GID} ${IOC} ${IOC}
COPY --from=developer ${SUPPORT}/configure ${SUPPORT}/configure
