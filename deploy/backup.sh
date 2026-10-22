#!/bin/sh
set -eu
umask 077
destination="${1:-./backups}"
mkdir -p "$destination"
temporary="$(mktemp "$destination/.sersi-backup.XXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
docker compose exec -T web python manage.py backup_catalogue --stdout > "$temporary"
filename="$destination/SERSI-Notice-$(date +%Y%m%d-%H%M%S)-$$.zip"
mv -- "$temporary" "$filename"
printf 'Sauvegarde créée : %s\n' "$filename"
