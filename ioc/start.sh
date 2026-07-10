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

# generate pvi device and template for Aravis cameras parameters ******************************

ibek_src="${CONFIG_DIR}/ioc.yaml"
readarray entities < <(yq -o=j -I=0 '.entities[]' "${ibek_src}")

for ((count = 0 ; count < ${#entities[@]}; count++ )); do # Iterate over each entity
    # Only process ADAravis cameras
    instance_type=$(yq -r ".entities[${count}].type" "${ibek_src}")

    [[ ${instance_type} != "ADAravis.aravisCamera" ]] && continue

    instance_class_from_config=$(yq -r ".entities[${count}].CLASS" "${ibek_src}")
    instance_prefix=$(yq -r ".entities[${count}].P" "${ibek_src}")

    # PVI device name follows the same convention as ADAravis.ibek.support.yaml:
    # always ADAravis-${P} (to keep techui-support simple)
    pvi_device_name="ADAravis-${instance_prefix}"
    template_file="/epics/support/ADGenICam/db/${pvi_device_name}.template"
    label="GenICam ${instance_prefix}"

    if [[ ${instance_class_from_config} == "AutoADGenICam" ]]; then
        # Auto generation for CLASS=AutoADGenICam
        instance_id=$(yq -r ".entities[${count}].ID" "${ibek_src}")
        xml_file="/tmp/${instance_id}-genicam.xml"
        arv-tool-0.8 -a "${instance_id}" genicam > "${xml_file}"

        if [[ -s ${xml_file} ]]; then
            # Generate pvi device from GenICam XML, embedded in a copy of ADAravis as subscreen
            python /epics/ioc/scripts/makePvi.py \
                --input_xml_file "${xml_file}" \
                --output_folder "/epics/pvi-defs/" \
                --pvi_device_name "${pvi_device_name}" \
                --label "${label}" \
                --embed_in "ADAravis"

            # Make GenICam template file from the GenICam XML
            python /epics/support/ADGenICam/scripts/makeDb.py \
                "${xml_file}" \
                "${template_file}"

            continue
        fi
    fi

    # Fallback for CLASS != AutoADGenICam or AutoADGenICam but XML generation failed:
    # Output generic ADAravis template and device pvi
    echo "Falling back to generic ADAravis template and device pvi for ${instance_prefix} (CLASS=${instance_class_from_config})"

    # Create fallback template_file from aravisCamera.template.
    # The check that template_file  doesn't exist already isn't really necessary now,
    # but just in case one day we set template_file to a pre-defined template,
    # in which case we wouldn't want to copy aravisCamera.template over it 
    if [[ ! -f ${template_file} ]]; then
        cp "/epics/support/ADAravis/db/aravisCamera.template" "${template_file}"
    fi

    # Create fall back pvi_device_name.
    # In theory we could generate it from template_file like below
    # pvi convert device --template "${template_file}" --name "${pvi_device_name}" --label "${label}" /epics/pvi-defs/
    # but it's better to use makePvi.py to create it from ADAravis.device.pvi.yaml
    # because the result will have any tweaking we put into makePvi.py.
    python /epics/ioc/scripts/makePvi.py \
        --input_xml_file "" \
        --output_folder "/epics/pvi-defs/" \
        --pvi_device_name "${pvi_device_name}" \
        --label "${label}" \
        --embed_in "ADAravis"
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

