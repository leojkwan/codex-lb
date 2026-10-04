## 1. Reproduce

- [x] 1.1 Reuse upstream native-worker asyncio/uvloop rollback/close and invalidated-watchdog regressions; retain actual RED against unchanged base.

## 2. Backport

- [x] 2.1 Guard watchdog listeners against invalidated/closed connection metadata access.
- [x] 2.2 Reuse bounded completion observation, closed-handle guard and honest diagnostics while preserving captured-connection cleanup ownership.

## 3. Verify

- [x] 3.1 Run focused GREEN and the full assigned database-session suite, including unsuccessful/pending teardown, cancellation and shutdown ownership.
- [ ] 3.2 Validate the scoped OpenSpec strictly and inspect exact changed paths.
- [x] 3.3 Leave uncommitted source and evidence with identities, commands, RED/GREEN and known gaps for parent review.

Validation wake: an existing OpenSpec validator becomes available; run `openspec validate backport-sqlite-cleanup-grace --strict --no-interactive` in this worktree, retain its actual result, and resume parent review. The current attempt returned rc 127 because `openspec` is absent. Do not archive or call the change ready until validation succeeds.
