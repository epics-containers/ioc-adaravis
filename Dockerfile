# Add support for GigE cameras with the ADAravis support module

##### build stage ##############################################################

FROM ghcr.io/epics-containers/epics-base-linux-developer:work AS developer

# install additional packages
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libboost-all-dev \
    libglib2.0-dev \
    libusb-1.0-0-dev \
    libxml2-dev \
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
    rm -fr /usr/local/aravis \
    echo /usr/local/lib64 > /etc/ld.so.conf.d/usr.conf && \
    ldconfig


# get and build the required support modules
WORKDIR ${SUPPORT}
COPY patch patch
COPY modules.py *modules.yaml .
RUN python3 modules.py install adaravis.ibek.modules.yaml

# update the generic IOC Makefile to include the new support
COPY Makefile ${IOC}/iocApp/src
RUN make -C ${IOC} && make -C ${IOC} clean

ENV DEV_PROMPT=IOC-ADARAVIS

##### runtime preparation stage ################################################

FROM developer AS runtime_prep

# get the products from the build stage and reduce to runtime assets only 
WORKDIR /min_files
RUN bash ${SUPPORT}/minimize.sh ${IOC} $(ls -d ${SUPPORT}/*/) 

##### runtime stage #############################################################

FROM ghcr.io/epics-containers/epics-base-linux-runtime:work AS runtime

# install runtime libraries from additional packages section above
RUN apt-get update -y && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libglib2.0-bin \
    libusb-1.0-0 \
    libxml2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=developer /usr/local/lib/x86_64-linux-gnu/libaravis* /usr/local/lib/x86_64-linux-gnu/
ENV LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/usr/local/lib/x86_64-linux-gnu/

# get the products from the build stage
COPY --from=runtime_prep /min_files /
