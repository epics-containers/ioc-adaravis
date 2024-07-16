#!/bin/bash

description='

 The epics-containers IOC Startup Script
 =======================================

 This script is used to start an EPICS IOC in a Kubernetes pod. Implementers
 of generic IOCs are free to replace this script with their own. But
 this script as is should work for most IOCs.

 When a generic IOC runs in a kubernetes pod it is expected to have
 a config folder that defines the IOC instance.
 The helm chart for the generic IOC will mount the config folder
 as a configMap and this turns a generic IOC into a specific IOC instance.

 Here we support the following set of options for the contents of
 the config folder:

 1. start.sh ******************************************************************
    If the config folder contains a start.sh script it will be executed.
    This allows the instance implementer to provide a completely custom
    startup script. Any other files that the script needs can also be placed
    in the config folder.

    The presence of this file overrides all other options.

    WARNING: config maps are restricted to 1MB total.

 2. ioc.yaml *************************************************************
    If the config folder contains a yaml file we invoke the ibek tool to
    generate the startup script and database. Then launch with the generated
    startup script. The file name should always be 'ioc.yaml'. The ioc instance
    can determine its own name with the following as the first line in 'ioc.yaml'

        ioc_name: ""{{ __utils__.get_env('IOC_NAME') }}""

    at the top of the file and in turn "{{ ioc_name }}"" can be used in any
    of the fields within the file. For example: by default Kubernetes will be
    looking at the iocStats PV IOC_NAME:Uptime to validate health of the IOC,
    therefore most IOC instances should include:

        entities:
        - type: epics.EpicsEnvSet
            name: EPICS_TZ
            value: "GMT0BST"

        - type: devIocStats.iocAdminSoft
            IOC: "{{ ioc_name | upper }}"

 3. st.cmd + ioc.subst *********************************************************
    If the config folder contains a st.cmd script and a ioc.subst file then
    optionally generate ioc.db from the ioc.subst file and use the st.cmd script
    as the IOC startup script. Note that the expanded database file will
    be generated in ${RUNTIME_DIR}/ioc.db

 4. empty config folder *******************************************************
    If the config folder is empty this message will be displayed.

 RTEMS IOCS - RTEMS IOC startup files can be generated using any of the above.

 For RTEMS we do not execute the ioc inside of the pod. Instead we:
  - copy the IOC directory to the RTEMS mount point
  - send a reboot command to the RTEMS crate
  - start a telnet session to the RTEMS IOC console and connect that to
    stdio of the pod.

'

# error reporting *************************************************************

function ibek_error {
    echo "${1}"

    # Wait for a bit so the container does not exit and restart continually
    sleep 120
}

# environment setup ************************************************************

# log commands and stop on errors
set -xe

cd ${IOC}
CONFIG_DIR=${IOC}/config

# add module paths to environment for use in ioc startup script
if [[ -f ${SUPPORT}/configure/RELEASE.shell ]]; then
    source ${SUPPORT}/configure/RELEASE.shell
fi

# override startup script
override=${CONFIG_DIR}/start.sh
# source YAML for IOC Builder for EPICS on Kubernetes (ibek)
ibek_yamls=(${CONFIG_DIR}/*.yaml)
# Startup script for EPICS IOC generated by ibek
ioc_startup=${CONFIG_DIR}/st.cmd

# folder for runtime assets
export RUNTIME_DIR=${EPICS_ROOT}/runtime
mkdir -p ${RUNTIME_DIR}

# expanded database file
epics_db=${RUNTIME_DIR}/ioc.db

# in case there are multiple YAML, pick the first one in the glob
ibek_src=${ibek_yamls[0]}

if [ -d ${CONFIG_DIR} ]; then
    echo "checking config folder ${CONFIG_DIR}"
    ls -al ${CONFIG_DIR}
else
    echo "ERROR: No config folder found."
    ibek_error "${description}"
fi

# 1. start.sh override script **************************************************
if [ -f ${override} ]; then
    exec bash ${override}
# 2. ioc.yaml ******************************************************************
elif [ -f ${ibek_src} ]; then

    if [[ ${#ibek_yamls[@]} > 1 ]]; then
        ibek_error "ERROR: Multiple YAML files found in ${CONFIG_DIR}."
    fi

    # Database generation script generated by ibek
    db_src=${RUNTIME_DIR}/ioc.subst
    final_ioc_startup=${RUNTIME_DIR}/st.cmd

    readarray entities < <(yq -o=j -I=0 '.entities[]' ${ibek_src})
    for ((count = 0 ; count < ${#entities[@]} ; count++ ))  # Interate over each entity
    do
        instance_type=$(yq .entities[${count}].type ${ibek_src})
        if [ $instance_type = "ADAravis.aravisCamera" ]
        then
            instance_class=$(yq .entities[${count}].CLASS ${ibek_src})
            instance_id=$(yq .entities[${count}].ID ${ibek_src})

            if [[ $instance_class == "AutoADGenICam" ]]; then
                instance_class=${instance_id}-${instance_class}
                # Auto generate GenICam database from camera parameters XML
                arv-tool-0.8 -a ${instance_id} genicam > /tmp/${instance_id}-genicam.xml
                python /epics/support/ADGenICam/scripts/makeDb.py /tmp/${instance_id}-genicam.xml /epics/support/ADGenICam/db/${instance_class}.template
            fi
            # Generate pvi device from the GenICam DB
            template=/epics/support/ADGenICam/db/$instance_class.template
            pvi convert device --template $template --name $instance_class --label "GenICam $instance_id" /epics/pvi-defs/
        fi
    done

    # get the ibek support yaml files this ioc's support modules
    defs=/epics/ibek-defs/*.ibek.support.yaml
    ibek runtime generate ${ibek_src} ${defs}

    # build expanded database using msi
    if [ -f ${db_src} ]; then
        includes=$(for i in ${SUPPORT}/*/db; do echo -n "-I $i "; done)
        bash -c "msi -o${epics_db} ${includes} -I${RUNTIME_DIR} -S${db_src}"
    fi

# 3. st.cmd + ioc.subst ************************************************
elif [ -f ${ioc_startup} ] ; then

    if [ -f ${CONFIG_DIR}/ioc.subst ]; then
        # generate ioc.db from ioc.subst, including all templates from SUPPORT
        includes=$(for i in ${SUPPORT}/*/db; do echo -n "-I $i "; done)
        msi ${includes} -I${RUNTIME_DIR} -S ${CONFIG_DIR}/ioc.subst -o ${epics_db}
    fi
    final_ioc_startup=${ioc_startup}
# 4. incorrect config folder ***************************************************
else
    ibek_error "
    ${description}

    ERROR: No IOC Instance Startup Assets found in ${CONFIG_DIR}
    Please add ioc.yaml to the config folder (or see above for other options).
    "
fi

# Launch the IOC ***************************************************************

if [[ ${EPICS_TARGET_ARCH} == "linux-x86_64" ]] ; then
    # Execute the IOC binary and pass the startup script as an argument
    exec ${IOC}/bin/linux-x86_64/ioc ${final_ioc_startup}
else
    # for not native architectures use the appropriate python package
    if [[ -f ${CONFIG_DIR}/proxy-start.sh ]]; then
        # instances can provide proxy-start.sh to override default behavior
        bash ${CONFIG_DIR}/proxy-start.sh
    else
        # the RTEMS container provides a python package to:
        # - copy binaries to the IOC's shared folder
        # - remotely configure the boot parameters
        # - remotely launch the IOC
        rtems-proxy start
    fi
fi


