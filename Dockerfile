ARG IMAGE_EXT

ARG BASE=7.0.8ad3
ARG REGISTRY=ghcr.io/epics-containers
ARG RUNTIME=${REGISTRY}/epics-base${IMAGE_EXT}-runtime:${BASE}
ARG DEVELOPER=${REGISTRY}/epics-base${IMAGE_EXT}-developer:${BASE}

##### build stage ##############################################################
FROM  ${DEVELOPER} AS developer

# Add missing dependancies
RUN curl -o /usr/bin/yq -L https://github.com/mikefarah/yq/releases/download/v4.44.2/yq_linux_amd64 && chmod +x /usr/bin/yq

# The devcontainer mounts the project root to /epics/generic-source
# Using the same location here makes devcontainer/runtime differences transparent.
ENV SOURCE_FOLDER=/epics/generic-source
# connect ioc source folder to its know location
RUN ln -s ${SOURCE_FOLDER}/ioc ${IOC}

# Get the current version of ibek
COPY requirements.txt requirements.txt
RUN pip install --upgrade -r requirements.txt

WORKDIR ${SOURCE_FOLDER}/ibek-support

COPY ibek-support/_ansible _ansible
ENV PATH=$PATH:${SOURCE_FOLDER}/ibek-support/_ansible

COPY ibek-support/iocStats/ iocStats
RUN ansible.sh iocStats

COPY ibek-support/asyn/ asyn
RUN ansible.sh asyn

COPY ibek-support/busy/ busy
RUN ansible.sh busy

COPY ibek-support/pvlogging/ pvlogging/
RUN ansible.sh pvlogging

COPY ibek-support/autosave/ autosave
RUN ansible.sh autosave

COPY ibek-support/sscan/ sscan
RUN ansible.sh sscan

COPY ibek-support/calc/ calc
RUN ansible.sh calc

COPY ibek-support/autosave/ autosave
RUN ansible.sh autosave

COPY ibek-support/ADCore/ ADCore
RUN ansible.sh ADCore

COPY ibek-support/ADGenICam/ ADGenICam/
RUN ansible.sh ADGenICam

COPY ibek-support/ADAravis/ ADAravis/
RUN ansible.sh ADAravis

COPY ibek-support/ffmpegServer/ ffmpegServer
RUN ansible.sh ffmpegServer

# get the ioc source and build it
COPY ioc ${SOURCE_FOLDER}/ioc
RUN ansible.sh ioc

# allow generated genicam files to be written for non root runtime user id
RUN chmod a+rw -R /epics/pvi-defs /epics/support/ADGenICam/db \
    /epics/generic-source/ibek-support

##### runtime preparation stage ################################################
FROM developer AS runtime_prep

# get the products from the build stage and reduce to runtime assets only
RUN ibek ioc extract-runtime-assets /assets /usr/local/lib/x86_64-linux-gnu

##### runtime stage ############################################################
FROM ${RUNTIME} AS runtime

# get runtime assets from the preparation stage
COPY --from=runtime_prep /assets /
COPY --from=runtime_prep /usr/bin/yq /usr/bin/yq

# install runtime system dependencies, collected from install.sh scripts
RUN ibek support apt-install-runtime-packages

CMD ["bash", "-c", "stdio-expose ${IOC}/start.sh"]
