#!/bin/bash

# A script for building EPICS container images.
#
# Note that this is implemented in bash to make it portable between
# CI frameworks. This approach uses the minimum of GitHub Actions.
# Also works locally for testing outside of CI (with podman-docker installed)
#
# INPUTS:
#   PUSH: if true, push the container image to the registry
#   TAG: the tag to use for the container image
#   REGISTRY: the container registry to push to
#   REPOSITORY: the container repository to push to
#   CACHE: the directory to use for caching

ARCH=${ARCH:-linux}
PUSH=${PUSH:-false}
TAG=${TAG:-latest}
REGISTRY=${REGISTRY:-ghcr.io}
if [[ -z ${REPOSITORY} ]] ; then
    # For local builds, infer the registry from git remote (assumes ghcr)
    REPOSITORY=$(git remote -v | sed   "s/.*@github.com:\(.*\) \(.*\)*/\1/" | tail -1)
    echo "inferred registry ${REPOSITORY}"
fi

NEWCACHE=${CACHE}-new

if ! docker -v 2> /dev/null; then
    echo "switching to podman ..."
    docker=podman
    shopt -s expand_aliases
    alias docker=podman

    # podman command line parameters (just use local cache)
    cachefrom=""
    cacheto=""
else
    docker=docker
    # setup a buildx driver for multi-arch / remote cached builds
    docker buildx create --driver docker-container --use
    # docker command line parameters
    cachefrom=--cache-from=type=local,src=${CACHE}
    cacheto=--cache-to=type=local,dest=${NEWCACHE},mode=max
fi

set -e

do_build() {
    ARCHITECTURE=$1
    TARGET=$2
    shift 2

    image_name=${REGISTRY}/${REPOSITORY}-${ARCHITECTURE}-${TARGET}:${TAG}
    # convert to lowercase - required for OCI URLs
    image_name=${image_name,,}
    args="
        --build-arg TARGET_ARCHITECTURE=${ARCHITECTURE}
        --target ${TARGET}
        -t ${image_name}
    "

    if [[ $docker != "podman" ]] ; then
        if [[ ${PUSH} == "true" ]] ; then
            args="--push "${args}
        else
            args="--load "${args}
        fi
    fi

    echo "CONTAINER BUILD FOR ${image_name} with ARCHITECTURE=${ARCHITECTURE} ..."

    (
        set -x
        $docker buildx build ${args} ${*} .
    )

    if [[ ${PUSH} == "true" && $docker == "podman" ]] ; then
        podman push ${image_name}
    fi
}

# EDIT BELOW FOR YOUR BUILD MATRIX REQUIREMENTS
#
# All builds should use cachefrom and the last should use cacheto
# The last build should execute all stages for the cache to be fully useful.
#
# intermediate builds should use cachefrom but will also see the local cache
#
# If None of the builds use all stages in the Dockerfile then consider adding
# cache-to to more than one build. But note there is a tradeoff in performance
# as every layer will get uploaded to the cache even if it just came out of the
# cache.

do_build ${ARCH} developer ${cachefrom}
do_build ${ARCH} runtime ${cachefrom} ${cacheto}


if [[ $docker != "podman" ]] ; then
    # remove old cache to avoid indefinite growth
    rm -rf ${CACHE}
    mv ${NEWCACHE} ${CACHE}
fi

# get the schema file from the developer container
echo "Getting schema file from developer container ..."
id=$($docker create ${image_name})
# convention for schema name is module.ibek.ioc.schema.json
# we get this my removing the ioc- prefix from the module name
SCHEMA=$(basename ${REPOSITORY} | sed 's/^ioc-//').ibek.ioc.schema.json
$docker cp $id:/epics/ioc/${SCHEMA} .
$docker rm -v $id
echo "schema file(s): $(ls *.ibek.ioc.schema.json)"
