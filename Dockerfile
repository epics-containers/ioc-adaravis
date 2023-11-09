##### build stage ##############################################################

ARG TARGET_ARCHITECTURE
ARG BASE=7.0.7ec2
ARG REGISTRY=ghcr.io/epics-containers

FROM  ${REGISTRY}/epics-base-${TARGET_ARCHITECTURE}-developer:${BASE} AS developer

# Get latest ibek while in development. Will come from epics-base
RUN pip install --upgrade ibek==1.5.0b3

# the devcontainer mounts the project root to /epics/ioc-adaravis
WORKDIR /epics/ioc-adaravis/ibek-support

# copy the global ibek files
COPY ibek-support/_global/ _global

COPY ibek-support/iocStats/ iocStats
RUN iocStats/install.sh 3.1.16

COPY ibek-support/asyn/ asyn/
RUN asyn/install.sh R4-42

COPY ibek-support/autosave/ autosave/
RUN autosave/install.sh R5-10-2

COPY ibek-support/busy/ busy/
RUN busy/install.sh R1-7-3

COPY ibek-support/sscan/ sscan/
RUN sscan/install.sh R2-11-6

COPY ibek-support/calc/ calc/
RUN calc/install.sh R3-7-5

COPY ibek-support/ADCore/ ADCore/
RUN ADCore/install.sh R3-12-1

COPY ibek-support/ADGenICam/ ADGenICam/
RUN ADGenICam/install.sh R1-9

COPY ibek-support/ADAravis/ ADAravis/
RUN ADAravis/install.sh R2-3

COPY ibek-support/autosave/ autosave/
RUN autosave/install.sh R5-11

# create IOC source tree, generate Makefile and compile IOC Instance
RUN ibek ioc build

##### runtime preparation stage ################################################

FROM developer AS runtime_prep

# get the products from the build stage and reduce to runtime assets only
RUN ibek ioc extract-runtime-assets /assets --extras /usr/local/lib/x86_64-linux-gnu

##### runtime stage ############################################################

FROM ${REGISTRY}/epics-base-${TARGET_ARCHITECTURE}-runtime:${BASE} AS runtime

# get runtime assets from the preparation stage
COPY --from=runtime_prep /assets /

# install runtime system dependencies, collected from install.sh scripts
RUN ibek support apt-install --runtime

ENV TARGET_ARCHITECTURE ${TARGET_ARCHITECTURE}

ENTRYPOINT ["/bin/bash", "-c", "${IOC}/start.sh"]
