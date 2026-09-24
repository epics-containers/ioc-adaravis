#!/bin/bash
TOP=/epics/ioc
cd ${TOP}
CONFIG_DIR=${TOP}/config

set -ex

TMP_DIR=/tmp
THIS_SCRIPT=$(realpath ${0})
override=${CONFIG_DIR}/startup.sh

# 'startup.sh' may be overridden in the ioc/config directory
# compare resolved paths: /epics/ioc is a symlink, so an unresolved override
# path never equals THIS_SCRIPT and a copied script would exec itself forever
if [[ -f ${override} && $(realpath "${override}") != "${THIS_SCRIPT}" ]]; then
    exec bash ${override}
fi

# Wait for the ibek doWait command to have completed successfully.
# This loop prevents the pod from unnecessarily reporting failed k8s startup probe events
# (for example, by exiting and trying again) while the IOC is still in the process of starting up.
while [ ! -f ${TMP_DIR}/doWait_completed.txt ]; do
    sleep 1
done

exit 0
