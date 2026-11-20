#!/usr/bin/env bash
# Existing installation only: preserve its Compose project and persistent data.
set -euo pipefail
umask 077

revision=${1:?Expected a Git commit SHA}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
app=/opt/scam-arena
release="/opt/scam-arena-releases/$revision"
archive="/root/scam-arena-$revision.tar.gz"
backup_dir=/opt/scam-arena-backups

command -v rsync >/dev/null
command -v flock >/dev/null
exec 9>/var/lock/scam-arena-deploy.lock
flock -w 3600 9
test -s "$app/.env"
test -f "$app/compose.yaml"
test -s "$archive"

# Refuse to deploy to a new/empty database volume by accident.
docker inspect scam-arena-db --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' | grep -Fxq scam-arena_postgres-data
test "$(docker inspect scam-arena-db --format '{{.State.Health.Status}}')" = healthy

mkdir -p "$release" "$backup_dir"
tar -xzf "$archive" -C "$release"
test -f "$release/compose.yaml"
test -f "$release/Dockerfile"

# Keep the running installation untouched if the new images cannot build.
docker compose -p scam-arena --env-file "$app/.env" -f "$release/compose.yaml" build scam-arena rasa

cd "$app"
backup="$backup_dir/$(date -u +%Y%m%dT%H%M%SZ)-$revision.dump"
docker compose -p scam-arena exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' > "$backup.tmp"
test -s "$backup.tmp"
mv "$backup.tmp" "$backup"

# Only synchronize source: credentials, models, reviews and backups stay on VPS.
# Exclusions also protect these paths from --delete.
rsync -a --delete \
  --exclude='/.env' --exclude='/.env.*' \
  --exclude='/voices/' --exclude='/.git/' \
  --exclude='/rasa/evaluation/.local/' \
  --exclude='/deployment/database.dump' \
  "$release/" "$app/"

docker compose -p scam-arena up -d --no-build --wait --wait-timeout 240 scam-arena
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8000/health
printf '\n%s\n' "$revision" > "$app/.deployed-revision"
printf '\nDeployed %s. Database backup: %s\n' "$revision" "$backup"
