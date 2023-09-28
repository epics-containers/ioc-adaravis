##### build stage ##############################################################

ARG TARGET_ARCHITECTURE
ARG BASE=7.0.7ec1
ARG REGISTRY=ghcr.io/epics-containers

FROM  ${REGISTRY}/epics-base-${TARGET_ARCHITECTURE}-developer:${BASE} AS developer

# In a devcontainer this folder is mounted on the host's clone of ioc-adsimdetector
WORKDIR /workspaces/ioc-adsimdetector/ibek-support

# During Development get latest ibek - TODO stable version will be in epics-base
RUN pip install --upgrade ibek

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

COPY ibek-support/ADCore/ ADCore/
RUN ADCore/install.sh R3-12-1

COPY ibek-support/ADAravis/ ADAravis/
RUN ADAravis/install.sh R2-3

# add startup scripts
COPY ioc ${IOC}

# Make the IOC
RUN ibek ioc generate-makefile
RUN ibek ioc compile

# create a schema file for the IOC
RUN bash -c "ibek ioc generate-schema */*ibek.support.yaml --output ${IOC}/adaravis.ibek.ioc.schema.json"

##### runtime preparation stage ################################################

FROM developer AS runtime_prep

# get the products from the build stage and reduce to runtime assets only
WORKDIR /min_files
RUN bash /epics/scripts/minimize.sh ${IOC} $(ls -d ${SUPPORT}/*/)

##### runtime stage ############################################################

FROM ${REGISTRY}/epics-base-${TARGET_ARCHITECTURE}-runtime:${BASE} AS runtime

# get the virtual environment from the developer stage
COPY --from=developer /venv /venv
# add products from build stage
COPY --from=runtime_prep /min_files /
# get the Aravis library we built
COPY --from=developer /usr/local/lib/x86_64-linux-gnu/libaravis-0.8.so.0 /usr/local/lib/x86_64-linux-gnu/
# get the ibek-support folders for accessing the SUPPORT YAML files
COPY --from=developer /workspaces /workspaces

# install runtime system dependencies, collected from install.sh scripts
RUN ibek support apt-install --runtime

# add startup scripts
COPY ioc ${IOC}

ENV TARGET_ARCHITECTURE ${TARGET_ARCHITECTURE}

ENTRYPOINT ["/bin/bash", "-c", "${IOC}/start.sh"]
