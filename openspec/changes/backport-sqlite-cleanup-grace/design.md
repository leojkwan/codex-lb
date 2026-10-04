## Context

This is an installed-version backport on base 84fde5a1ed5e0d5a58ccb3ec4b82938b059bf8c5. The existing file-backed SQLite teardown snapshot, fence, cleanup registry and shutdown drain remain the ownership path.

## Goals / Non-Goals

Reuse the pinned upstream diagnostic guard and completion observation. Preserve the 1.24.0 setup and dependency contract. Broader upstream startup/runstate, PostgreSQL, shared-future, schema and application lifecycle changes are outside scope.

## Decisions

- Use the upstream listener-local metadata guard at every connection-metadata listener call site; pool-record metadata retains its existing access.
- Reuse `_shielded_bounded` for the same teardown task during a fixed 0.75-second grace. A successful result alone exempts reclamation; exceptions, cancellation and pending work retain the captured-connection path.
- Retain the existing initial bounded wait and cancellation behavior. Both rollback and close use the same completion decision.
- Skip closed captured handles, report observed failures, describe interruption/invalidation as attempts, and retain original and follow-up task ownership. A closed logical handle does not establish absence of a retained native cursor.
- Keep the existing bounded shutdown drain unchanged. No new settings or cleanup registry.

## Risks / Trade-offs

A genuinely pending teardown can take an additional 0.75 seconds before reclamation. Native task completion and event-loop observation are separate witnesses. Failed invalidation and closed-handle exceptions do not prove permanent writer retention or release.

## Verification

Run unchanged upstream real-worker starvation tests under asyncio and uvloop for rollback and close, and the native invalidated-watchdog rollback control, against unchanged source first. Then run them and the full assigned database-session suite after the backport. Existing pending-reclaim, cancellation and shutdown-owner tests remain the controls for unsuccessful cleanup.
