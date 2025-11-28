#!/bin/bash

# wrap the console *************************************************************

if [[ -n ${KUBERNETES_PORT} && -z ${STDIO_EXPOSED} ]]; then
    STDIO_EXPOSED=YES exec stdio-socket ${IOC}/start.sh
    exit 0
fi

# error reporting **************************************************************

function ibek_error {
    echo "Error on line $BASH_LINENO: $BASH_COMMAND (exit code: $?)"

    # Wait for a bit so the container does not exit and restart continually
    sleep 10
    exit 1
}

trap ibek_error ERR

# log commands and stop on errors
set -xe

# environment setup ************************************************************

cd ${IOC}

export CONFIG_DIR=${IOC}/config
export RUNTIME_DIR=${EPICS_ROOT}/runtime
mkdir -p ${RUNTIME_DIR}

# add module paths to environment for use in ioc startup script
if [[ -f ${SUPPORT}/configure/RELEASE.shell ]]; then
    source ${SUPPORT}/configure/RELEASE.shell
fi

# check for an override start.sh script ****************************************

if [ -f ${CONFIG_DIR}/start.sh ]; then
    exec bash ${CONFIG_DIR}/start.sh
fi

# copy hand coded files to runtime folder **************************************

for f in ioc.db ioc.subst st.cmd; do
    if [ -f ${CONFIG_DIR}/${f} ]; then
        cp ${CONFIG_DIR}/${f} ${RUNTIME_DIR}/
    fi
done

# copy any streamDevice protocol files to runtime folder ***********************

if [[ -d /epics/support/configure/protocol ]] ; then
    rm -fr ${RUNTIME_DIR}/protocol
    cp -r /epics/support/configure/protocol  ${RUNTIME_DIR}
fi

# generate template for Aravis cameras parameters ******************************

ibek_src=${CONFIG_DIR}/ioc.yaml
readarray entities < <(yq -o=j -I=0 '.entities[]' ${ibek_src})
for ((count = 0 ; count < ${#entities[@]} ; count++ ))  # Iterate over each entity
do
    instance_type=$(yq .entities[${count}].type ${ibek_src})
    if [ $instance_type = "ADAravis.aravisCamera" ]
    then
        instance_class=$(yq .entities[${count}].CLASS ${ibek_src})
        instance_id=$(yq .entities[${count}].ID ${ibek_src})

        if [[ $instance_class == "AutoADGenICam" ]]; then
            instance_class=auto-${instance_id}
            # Auto generate GenICam database from camera parameters XML
            arv-tool-0.8 -a ${instance_id} genicam > /tmp/${instance_id}-genicam.xml
            if [[ ! -s /tmp/${instance_id}-genicam.xml ]]; then
                # can't contact the camera - make an empty template
                echo "Can't connect to camera ${instance_id}"
                touch /epics/support/ADGenICam/db/${instance_class}.template
            else
                # make a db file from the GenICam XML
                python /epics/support/ADGenICam/scripts/makeDb.py /tmp/${instance_id}-genicam.xml /epics/support/ADGenICam/db/${instance_class}.template
            fi
        fi
        # Generate pvi device from the GenICam DB
        template=/epics/support/ADGenICam/db/$instance_class.template
        pvi convert device --template $template --name $instance_class --label "GenICam $instance_id" /epics/pvi-defs/
    fi
done

# get the ibek support yaml files this ioc's support modules
defs=/epics/ibek-defs/*.ibek.support.yaml
# prepare the runtime assets: ioc.db, st.cmd + protocol, autosave files
ibek runtime generate ${ibek_src} ${defs}
ibek runtime generate-autosave
if [[ -d /epics/support/configure/protocol ]] ; then
    rm -fr ${RUNTIME_DIR}/protocol
    cp -r /epics/support/configure/protocol  ${RUNTIME_DIR}
fi

# generate EPICS runtime assets ************************************************

if [[ -f ${CONFIG_DIR}/ioc.yaml ]] ; then
    ibek runtime generate2 ${CONFIG_DIR}
    ibek runtime generate-autosave
fi

# build expanded database using msi
if [ -f ${RUNTIME_DIR}/ioc.subst ]; then
    includes=$(for i in ${SUPPORT}/*/db; do echo -n "-I $i "; done)
    bash -c "msi -o${RUNTIME_DIR}/ioc.db ${includes} -I${RUNTIME_DIR} -S${RUNTIME_DIR}/ioc.subst"
fi

# Launch the IOC ***************************************************************

${IOC}/bin/linux-x86_64/ioc ${RUNTIME_DIR}/st.cmd

