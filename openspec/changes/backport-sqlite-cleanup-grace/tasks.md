## 1. Reproduce

- [x] 1.1 Reuse upstream native-worker asyncio/uvloop rollback/close and invalidated-watchdog regressions; retain actual RED against unchanged base.

## 2. Backport

- [x] 2.1 Guard watchdog listeners against invalidated/closed connection metadata access.
- [x] 2.2 Reuse bounded completion observation, closed-handle guard and honest diagnostics while preserving captured-connection cleanup ownership.

## 3. Verify

- [x] 3.1 Run focused GREEN and the full assigned database-session suite, including unsuccessful/pending teardown, cancellation and shutdown ownership.
- [x] 3.2 Validate the scoped OpenSpec strictly and inspect exact changed paths.
- [x] 3.3 Leave uncommitted source and evidence with identities, commands, RED/GREEN and known gaps for parent review.

## 4. Diagnostic correction (lb-sq02-diagnostic-correction-20261004)

- [x] 4.1 Run the unchanged parent diagnostic falsifier against assigned base b5f94cb6d7e15e7e858028b93a18374619adae91; retain actual D1/D2 RED and consumed source identity.
- [x] 4.2 Exercise refused invalidation and bounded shutdown over a real peer writer; strengthen existing late-exception and closed-handle assertions.
- [x] 4.3 Correct only shutdown wording and the common observed-failure warning boundary; preserve grace, watchdog and cleanup ownership.
- [x] 4.4 Run diagnostic GREEN, full assigned database-session tests and the available strict scoped validator; retain commands, identities and ordinary-file evidence for parent review.

The parent retains archive, source landing, runtime adoption and acceptance. The existing validator is available; no installation or global configuration is needed.
