#!/usr/bin/env bash
set -euo pipefail

release_sha=${1:?Provide the release commit SHA}
image_prefix=${2:?Provide the GHCR image prefix}
# Free space needed before pulling a release; one pair of images takes about 1.5 GB.
min_free_mb=3072
cd "$HOME/masterly"

exec 9>"$(git rev-parse --git-path masterly-deploy.lock)"
flock -w 120 9

if [[ $(git branch --show-current) != main || -n $(git status --porcelain --untracked-files=no) ]]; then
    echo 'The EC2 checkout must be on main with no tracked changes.' >&2
    exit 1
fi

GIT_TERMINAL_PROMPT=0 git fetch origin main
if [[ $(git rev-parse FETCH_HEAD) != "$release_sha" ]]; then
    echo "Skipping $release_sha because main has advanced."
    exit 0
fi
git merge --ff-only "$release_sha"

export MASTERLY_BACKEND_IMAGE="${image_prefix}-backend:${release_sha}"
export MASTERLY_WEB_IMAGE="${image_prefix}-web:${release_sha}"

compose() {
    docker compose --env-file .env.deploy -f docker-compose.prod.yml -f deploy/compose.release.yml "$@" </dev/null
}

# Every docker call reads /dev/null: this script itself arrives on stdin.

# The release SHA a running service was started from; empty if it is not a release image.
running_release() {
    local id image
    id=$(compose ps -q "$1")
    [[ -n $id ]] || return 0
    image=$(docker inspect --format '{{.Config.Image}}' "$id" </dev/null)
    if [[ $image == "${image_prefix}-$1:"* ]]; then
        echo "${image##*:}"
    fi
}

# Removes this host's backend and web release images whose SHA is not an argument.
# Without --force, Docker keeps any image a container still uses.
remove_old_images() {
    local keep=" $* " image status=0
    for service in backend web; do
        while read -r image; do
            [[ -n $image && ${image##*:} != '<none>' && $keep != *" ${image##*:} "* ]] || continue
            docker image rm "$image" </dev/null || status=1
        done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' "${image_prefix}-${service}" </dev/null)
    done
    return "$status"
}

free_mb() {
    df --output=avail -k "$image_dir" | awk 'NR == 2 { print int($1 / 1024) }'
}

compose config --quiet
if ! domain=$(compose exec -T nginx printenv MASTERLY_HTTPS_DOMAIN) || [[ -z "$domain" ]]; then
    echo 'The running Nginx service must have MASTERLY_HTTPS_DOMAIN configured.' >&2
    exit 1
fi

image_dir=/var/lib/containerd
[[ -d $image_dir ]] || image_dir=$(docker info --format '{{.DockerRootDir}}' </dev/null)

# Successful releases, newest first: the one now serving and the one before it.
history_file=$(git rev-parse --git-path masterly-releases)
releases=()
if [[ -f $history_file ]]; then
    mapfile -t releases < "$history_file"
fi
backend_before=$(running_release backend)
web_before=$(running_release web)
if [[ ${#releases[@]} -eq 0 && -n $web_before ]]; then
    releases=("$web_before")
    echo "$web_before" > "$history_file"
fi

if (($(free_mb) < min_free_mb)); then
    echo "Only $(free_mb) MB free in $image_dir; removing old images before pulling."
    remove_old_images "$release_sha" $backend_before $web_before "${releases[@]}" ||
        echo 'Warning: some old images could not be removed.' >&2
    if (($(free_mb) < min_free_mb)); then
        echo "Not enough disk space: $(free_mb) MB free, $min_free_mb MB needed. No service was changed." >&2
        exit 1
    fi
fi

compose pull --policy always backend web
compose run --rm --no-deps --pull never -T backend alembic upgrade head
compose up -d --no-build --no-deps --pull never --wait backend
compose up -d --no-build --no-deps --pull never --wait web

curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-connrefused \
    --max-time 10 --output /dev/null "https://${domain}/api/auth/status"
echo "Deployed $release_sha and verified https://${domain}/api/auth/status"

# Keep this release and the previous successful one for a rollback.
previous=
for sha in "${releases[@]}"; do
    if [[ $sha != "$release_sha" ]]; then
        previous=$sha
        break
    fi
done
printf '%s\n' "$release_sha" ${previous:+"$previous"} > "$history_file"
remove_old_images "$release_sha" $previous ||
    echo 'Warning: some old images could not be removed.' >&2
echo "Kept releases: $release_sha ${previous}"
df -h "$image_dir"
