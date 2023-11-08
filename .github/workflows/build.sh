#!/bin/bash

# A generic build script for epics-containers ioc repositories
#
# Note that this is implemented in bash to make it portable between
# CI frameworks. This approach uses the minimum of GitHub Actions.
# Also works locally for testing outside of CI
#
# INPUTS:
#   PUSH: if true, push the container image to the registry
#   TAG: the tag to use for the container image
#   PLATFORM: the platform to build for (linux/amd64 or linux/arm64)

export EC_TAG="--tag ${TAG:-latest}"
export EC_PLATFORM="--platform ${PLATFORM:-linux/amd64}"
if [[ "${PUSH}" == 'true' ]] ; then EC_PUSH='--push' ; fi

THIS=$(dirname ${0})
set -xe

# get the current version of ec CLI
pip install -r ${THIS}/../../requirements.txt

# add extra cross compilation platforms below if needed  e.g.
#   ec dev build  --arch rtems ... for RTEMS cross compile

# build runtime and developer images
ec -v dev build ${EC_TAG} ${EC_PLATFORM} ${EC_PUSH}

# extract the ioc schema from the runtime image
ec dev launch-local ${EC_TAG} --execute \
'ibek ioc generate-schema /epics/ibek/*.ibek.support.yaml' > ibek.ioc.schema.json

# run acceptance tests
shopt -s nullglob # expand to nothing if no tests are found
for t in "${THIS}/../../tests/*.sh"; do ${t}; done

