## Why

Installed 1.24.0 can reclaim successful native SQLite teardown when its completion callbacks are delayed. Watchdog metadata reads can also reconnect an invalidated transaction before rollback. Reuse the independently proven corrections from upstream f8ffbac2099a113fba54dfd8d77774f5bca80ffa at the existing session boundary.

## What Changes

- Guard watchdog connection metadata access against invalidated and closed handles.
- Observe teardown success for a separate bounded completion grace before reclaiming captured connections.
- Skip already-closed captured handles while retaining failure reporting and owned cleanup.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `database-backends`: safe SQLite watchdog diagnostics and bounded teardown completion observation.

## Impact

Only `app/db/session.py` and its unit tests change. No schema, migration, dependency, version, authentication, routing, configuration or installed runtime changes.

## Non-goals

No full beta upgrade, periodic GC, universal retained-writer fix, production-outage attribution or deployment claim.
