#!/usr/bin/env bash
# Start a local Postgres 16 cluster for development in .data/pg (port 5433).
# Use docker-compose.yml instead if you prefer a container.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
DATA="$ROOT/.data/pg"
PORT="${LINTEL_PG_PORT:-5433}"
mkdir -p "$ROOT/.data"
# initdb refuses to run as root; in containers run the cluster as the postgres user.
AS=()
if [ "$(id -u)" = "0" ]; then
  chown postgres "$ROOT/.data"
  AS=(runuser -u postgres --)
fi
if [ ! -f "$DATA/PG_VERSION" ]; then
  "${AS[@]}" "$PGBIN/initdb" -D "$DATA" -U lintel --auth=trust -E UTF8 >/dev/null
  "${AS[@]}" sh -c "printf \"listen_addresses = '127.0.0.1'\nport = $PORT\nunix_socket_directories = '$ROOT/.data'\n\" >> '$DATA/postgresql.conf'"
fi
if ! "${AS[@]}" "$PGBIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then
  "${AS[@]}" "$PGBIN/pg_ctl" -D "$DATA" -l "$ROOT/.data/pg.log" -w start >/dev/null
fi
for db in lintel lintel_test; do
  psql -h 127.0.0.1 -p "$PORT" -U lintel -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    || psql -h 127.0.0.1 -p "$PORT" -U lintel -d postgres -c "CREATE DATABASE $db" >/dev/null
done
echo "postgres ready on 127.0.0.1:$PORT (databases: lintel, lintel_test)"
