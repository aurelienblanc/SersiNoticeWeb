#!/bin/sh
set -eu
destination="${1:-./backups}/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$destination"
chmod 700 "$destination"
docker compose stop proxy web
trap 'docker compose start web proxy >/dev/null' EXIT
docker compose exec -T db pg_dump -U sersi -d sersi --format=custom > "$destination/database.dump"
docker compose run --rm -T --no-deps --entrypoint tar web -C /data -czf - . > "$destination/documents.tar.gz"
printf 'Sauvegarde créée : %s\n' "$destination"
