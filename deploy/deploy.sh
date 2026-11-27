#!/usr/bin/env bash
set -euo pipefail

release_sha=${1:?Provide the release commit SHA}
image_prefix=${2:?Provide the GHCR image prefix}
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

compose config --quiet
if ! domain=$(compose exec -T nginx printenv MASTERLY_HTTPS_DOMAIN) || [[ -z "$domain" ]]; then
    echo 'The running Nginx service must have MASTERLY_HTTPS_DOMAIN configured.' >&2
    exit 1
fi

compose pull --policy always backend web
compose run --rm --no-deps --pull never -T backend alembic upgrade head
compose up -d --no-build --no-deps --pull never --wait backend
compose up -d --no-build --no-deps --pull never --wait web

curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-connrefused \
    --max-time 10 --output /dev/null "https://${domain}/api/auth/status"
echo "Deployed $release_sha and verified https://${domain}/api/auth/status"
