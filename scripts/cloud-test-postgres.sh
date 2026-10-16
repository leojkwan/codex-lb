#!/usr/bin/env bash
# Run `make test-postgres` in a container with no Docker (Claude cloud): a throwaway apt Postgres
# (CI uses postgres:16) on 127.0.0.1:5432 with the codex_lb/codex_lb/codex_lb credentials the
# Makefile defaults to. Usage: scripts/cloud-test-postgres.sh [make args]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
if [[ -z "$PGBIN" ]]; then
  [[ "$(id -u)" == 0 ]] || { echo "PostgreSQL is not installed and root is required to install it" >&2; exit 1; }
  apt-get install -y postgresql >&2
  PGBIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)"
fi
PORT="${CODEX_LB_TEST_PG_PORT:-5432}"
RUN="$(mktemp -d /tmp/codex-lb-pg.XXXXXX)"
as_pg() { if [[ "$(id -u)" == 0 ]]; then runuser -u postgres -- "$@"; else "$@"; fi; }
cleanup() {
  if ! as_pg "$PGBIN/pg_ctl" -D "$RUN/data" -m fast -w stop >/dev/null 2>&1 \
    && ! as_pg "$PGBIN/pg_ctl" -D "$RUN/data" -m immediate -w stop >/dev/null 2>&1; then
    # Do not delete the data directory under a server that is still running.
    if [[ -f "$RUN/data/postmaster.pid" ]]; then echo "warning: could not stop temporary PostgreSQL; keeping $RUN" >&2; return; fi
  fi
  rm -rf "$RUN"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
chmod a+rx "$RUN"; mkdir -p "$RUN/sock"; [[ "$(id -u)" != 0 ]] || chown postgres "$RUN" "$RUN/sock"
as_pg "$PGBIN/initdb" -D "$RUN/data" --username=postgres --auth=trust --no-locale --encoding=UTF8 >/dev/null
# max_connections is raised because the suite opens many pools.
as_pg "$PGBIN/pg_ctl" -D "$RUN/data" -o "-F -c listen_addresses=127.0.0.1 -c max_connections=200 -k $RUN/sock -p $PORT" -w start >/dev/null
as_pg "$PGBIN/psql" -X -v ON_ERROR_STOP=1 -h "$RUN/sock" -p "$PORT" -U postgres -d postgres -q <<'SQL'
create role codex_lb login superuser password 'codex_lb';
create database codex_lb owner codex_lb;
SQL
cd "$ROOT"
# Force the temporary database even if the caller exported an override.
DB_URL="postgresql+asyncpg://codex_lb:codex_lb@127.0.0.1:${PORT}/codex_lb"
CODEX_LB_TEST_DATABASE_URL="$DB_URL" make test-postgres POSTGRES_TEST_DATABASE_URL="$DB_URL" "$@"
