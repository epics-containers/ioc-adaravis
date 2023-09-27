#!/bin/bash

#
# The epics-containers IOC startup script.
#
# This script is used to start an EPICS IOC in a Kubernetes pod. Implementers
# of generic IOCs are free to replace this script with their own. But
# this script as is should work for most IOCs.
#
# When a generic IOC runs in a kubernetes pod it is expected to have
# a config folder that defines the IOC instance.
# The helm chart for the generic IOC will mount the config folder
# as a configMap and this turns a generic IOC into aspecific IOC instance.
#
# Here we support the following set of options for the contents of
# the config folder:
#
# 1. start.sh ******************************************************************
#    If the config folder contains a start.sh script it will be executed.
#    This allows the instance implementer to provide a conmpletely custom
#    startup script.
#
# 2. ioc.yaml *************************************************************
#    If the config folder contains an ioc.yaml file we invoke the ibek tool to
#    generate the startup script and database. Then launch with the generated
#    startup script.
#
# 3. st.cmd + ioc.subst *********************************************************
#    If the config folder contains a st.cmd script and a ioc.subst file then
#    optionally generate ioc.db from the ioc.subst file and use the st.cmd script
#    as the IOC startup script. Note that the expanded database file will
#    be generated in /tmp/ioc.db
#
# 4. empty config folder *******************************************************
#    If the config folder is not mounted then the IOC will launch the example in
#    ./config folder. Mounting a config folder overrides the example contents
#    in this repo's ./config/ .
#
# RTEMS IOCS - RTEMS IOC startup files can be generated using 2,3,4 above. For
# RTEMS we do not execute the ioc inside of the pod. Instead we:
#  - copy the IOC directory to the RTEMS mount point
#  - send a reboot command to the RTEMS crate
#  - start a telnet session to the RTEMS IOC console
#

set -x -e

# environment setup ************************************************************

TOP=/repos/epics/ioc
cd ${TOP}
CONFIG_DIR=${TOP}/config
THIS_SCRIPT=$(realpath ${0})

# add module paths to environment for use in ioc startup script
source ${SUPPORT}/configure/RELEASE.shell

# override startup script
override=${CONFIG_DIR}/start.sh
# source YAML for IOC Builder for EPICS on Kubernetes (ibek)
ibek_src=${CONFIG_DIR}/ioc.yaml
# Startup script for EPICS IOC generated by ibek
ioc_startup=${CONFIG_DIR}/st.cmd
# expanded database file
epics_db=/tmp/ioc.db


# 1. start.sh ******************************************************************

if [[ -f ${override} && ${override} != ${THIS_SCRIPT} ]]; then
    exec bash ${override}

# 2. ioc.yaml ******************************************************************

elif [ -f ${ibek_src} ]; then
    # Database generation script generated by ibek
    db_src=/tmp/make_db.sh
    final_ioc_startup=/tmp/st.cmd

    # get ibek the support yaml files this ioc's support modules
    defs=/ctools/*/*.ibek.support.yaml
    ibek build-startup ${ibek_src} ${defs} --out ${final_ioc_startup} --db-out ${db_src}

    # build expanded database using the db_src shell script
    if [ -f ${db_src} ]; then
        bash ${db_src} > ${epics_db}
    fi

# 3. st.cmd + ioc.substitutions ************************************************

elif [ -f ${ioc_startup} ] ; then
    if [ -f ${CONFIG_DIR}/ioc.substitutions ]; then
        # generate ioc.db from ioc.substitutions, including all templates from SUPPORT
        includes=$(for i in ${SUPPORT}/*/db; do echo -n "-I $i "; done)
        # msi tries to open substitutions file R/W so copy to a writable location
        cp ${CONFIG_DIR}/ioc.substitutions /tmp
        msi ${includes} -S /tmp/ioc.substitutions -o ${epics_db}
    fi
    final_ioc_startup=${ioc_startup}

# 4. empty config folder *******************************************************

else
    echo "ERROR - no startup script found in config folder"
    echo "${CONFIG_DIR} must contain one of st.cmd, ioc.yaml, start.sh"
fi

# Launch the IOC ***************************************************************

if [[ ${TARGET_ARCHITECTURE} == "rtems" ]] ; then

    # this mount point is defined in helm-ioc-lib _deployment.yaml
    K8S_IOC_ROOT=/nfsv2-tftp

    echo "RTEMS IOC. Copying IOCs files to RTEMS mount point ..."
    rm -rf ${K8S_IOC_ROOT}/*
    cp -r ${IOC}/* ${K8S_IOC_ROOT}
    mkdir -p ${K8S_IOC_ROOT}/support/db
    cp -r ${SUPPORT}/*/db/* ${K8S_IOC_ROOT}/support/db

    if [[ -f /tmp/ioc.db ]]; then
        cp /tmp/ioc.db ${K8S_IOC_ROOT}/config
    fi

    # Connect to the RTEMS console and reboot the IOC if requested
    echo "Connecting to RTEMS console at ${RTEMS_VME_CONSOLE_ADDR}:${RTEMS_VME_CONSOLE_PORT}"
    exec python3 /ctools/telnet3.py connect ${RTEMS_VME_CONSOLE_ADDR} ${RTEMS_VME_CONSOLE_PORT} --reboot ${RTEMS_VME_AUTO_REBOOT} --pause ${RTEMS_VME_AUTO_PAUSE}
else
    # Execute the IOC binary and pass the startup script as an argument
    exec ${IOC}/bin/linux-x86_64/ioc ${final_ioc_startup}
fi