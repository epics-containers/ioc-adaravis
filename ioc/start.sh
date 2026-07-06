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

generate_pvi_from_template() {
    local template="$1"
    local name="$2"
    local label="$3"

    pvi convert device \
        --template "${template}" \
        --name "${name}" \
        --label "${label}" \
        /epics/pvi-defs/
}

generate_pvi_from_template() {
    local template="$1"
    local output_asset_name="$2"
    local label="$3"

    pvi convert device \
        --template "${template}" \
        --name "${output_asset_name}" \
        --label "${label}" \
        /epics/pvi-defs/
}

ibek_src="${CONFIG_DIR}/ioc.yaml"
readarray entities < <(yq -o=j -I=0 '.entities[]' "${ibek_src}")

for ((count = 0 ; count < ${#entities[@]}; count++ )); do # Iterate over each entity
    # Only process ADAravis cameras
    instance_type=$(yq -r ".entities[${count}].type" "${ibek_src}")
    [[ ${instance_type} != "ADAravis.aravisCamera" ]] && continue

    instance_class_from_config=$(yq -r ".entities[${count}].CLASS" "${ibek_src}")
    instance_prefix=$(yq -r ".entities[${count}].P" "${ibek_src}")
    label="GenICam ${instance_prefix}" 
    output_asset_name="ADAravis-${instance_prefix}"
    auto_generated_template="/epics/support/ADGenICam/db/${output_asset_name}.template"

    if [[ ${instance_class_from_config} == "AutoADGenICam" ]]; then
        # Auto generation for CLASS=AutoADGenICam
        instance_id=$(yq -r ".entities[${count}].ID" "${ibek_src}")
        xml_file="/tmp/${instance_id}-genicam.xml"
        arv-tool-0.8 -a "${instance_id}" genicam > "${xml_file}"

        if [[ -s ${xml_file} ]]; then
            # Generate pvi device from GenICam XML, embedded in a copy of ADAravis as subscreen
            python /epics/ioc/scripts/makePvi.py \
                "${xml_file}" \
                "/epics/pvi-defs/" \
                --instance_class "${output_asset_name}" \
                --label "${label}" \
                --embed_in "ADAravis"

            # Make GenICam template file from the GenICam XML
            python /epics/support/ADGenICam/scripts/makeDb.py \
                "${xml_file}" \
                "${auto_generated_template}"

            continue
        fi
    fi

    # fallback for class != AutoADGenICam or AutoADGenICam with no XML
    echo "Generating blank GenICam assets for ${instance_prefix}"
    touch "${auto_generated_template}"
    generate_pvi_from_template \
        "${auto_generated_template}" \
        "${output_asset_name}" \
        "${label}"

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

