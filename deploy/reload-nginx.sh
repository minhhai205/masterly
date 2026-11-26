#!/bin/sh
set -eu

container_id=$(docker ps -q \
    --filter label=com.docker.compose.project=masterly-deploy \
    --filter label=com.docker.compose.service=nginx)

[ -n "$container_id" ] || exit 0
docker exec "$container_id" nginx -t
docker exec "$container_id" nginx -s reload
