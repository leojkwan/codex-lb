#!/usr/bin/env bash
# Run `make test-postgres` in a container with no Docker (Claude cloud): a throwaway apt Postgres
# (CI uses postgres:16) on 127.0.0.1:5432 with the codex_lb/codex_lb/codex_lb credentials the
# Makefile defaults to. Usage: scripts/cloud-test-postgres.sh [make args]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
if [[ -z "$PGBIN" ]]; then apt-get install -y postgresql >&2; PGBIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)"; fi
PORT="${CODEX_LB_TEST_PG_PORT:-5432}"
RUN="$(mktemp -d /tmp/codex-lb-pg.XXXXXX)"
as_pg() { if [[ "$(id -u)" == 0 ]]; then runuser -u postgres -- "$@"; else "$@"; fi; }
cleanup() { as_pg "$PGBIN/pg_ctl" -D "$RUN/data" -m fast -w stop >/dev/null 2>&1 || true; rm -rf "$RUN"; }
trap cleanup EXIT INT TERM
chmod a+rx "$RUN"; mkdir -p "$RUN/sock"; [[ "$(id -u)" != 0 ]] || chown postgres "$RUN" "$RUN/sock"
as_pg "$PGBIN/initdb" -D "$RUN/data" --username=postgres --auth=trust --no-locale --encoding=UTF8 >/dev/null
# max_connections is raised because the suite opens many pools.
as_pg "$PGBIN/pg_ctl" -D "$RUN/data" -o "-F -c listen_addresses=127.0.0.1 -c max_connections=200 -k $RUN/sock -p $PORT" -w start >/dev/null
as_pg "$PGBIN/psql" -X -v ON_ERROR_STOP=1 -h "$RUN/sock" -p "$PORT" -U postgres -d postgres -q <<'SQL'
create role codex_lb login superuser password 'codex_lb';
create database codex_lb owner codex_lb;
SQL
cd "$ROOT"
make test-postgres "$@"
