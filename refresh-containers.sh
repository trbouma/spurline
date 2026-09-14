#!/bin/sh

set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$repo_dir"

if ! git diff --quiet || ! git diff --cached --quiet; then
    printf '%s\n' 'Tracked working-tree changes are present; commit or stash them before refreshing.' >&2
    exit 1
fi

printf '%s\n' 'Pulling fast-forward changes...'
git pull --ff-only

printf '%s\n' 'Validating Docker Compose configuration...'
docker compose config --quiet

printf '%s\n' 'Building Spurline container image...'
docker compose build

printf '%s\n' 'Recreating Spurline container...'
docker compose up --force-recreate --detach

printf '%s\n' 'Spurline container refreshed.'
docker compose ps

printf '%s\n' 'Waiting for the Spurline health check...'
attempt=1
max_attempts=30
while ! docker compose exec -T spurline python -c \
    "import json, urllib.request; response = json.load(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)); assert response.get('status') == 'ok'" \
    >/dev/null 2>&1
do
    if [ "$attempt" -ge "$max_attempts" ]; then
        printf '%s\n' 'Spurline health check failed after 60 seconds.' >&2
        docker compose ps >&2
        docker compose logs --tail 50 spurline >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 2
done

printf '%s\n' 'Spurline health check passed: status=ok'
