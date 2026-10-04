## ADDED Requirements

### Requirement: SQLite watchdog diagnostics preserve invalidated transaction cleanup

SQLite watchdog callbacks MUST NOT access connection metadata in a way that reconnects an invalidated or closed connection. An invalidated transaction MUST be able to complete rollback without watchdog diagnostics raising PendingRollbackError.

#### Scenario: Rollback after connection invalidation

- **GIVEN** a SQLite connection with an active transaction and the write watchdog installed
- **WHEN** its driver connection is invalidated and the transaction is rolled back
- **THEN** rollback completes without diagnostic reconnection
- **AND** a subsequent query on the SQLAlchemy connection succeeds

### Requirement: Successful SQLite teardown receives bounded completion observation

When the initial bounded wait for file-backed SQLite rollback or close expires, the service MUST observe the same teardown task for a separate bounded 0.75-second completion grace. Only successful completion MUST exempt the session from fencing, interruption, invalidation and deferred cleanup registration. Normal remaining teardown MUST run. Failed, cancelled or still-pending teardown MUST retain captured-connection reclamation attempts and owned late cleanup. Already-closed captured handles MUST NOT be interrupted or invalidated again.

A successful-completion warning MUST name phase, initial bound and elapsed time measured before grace. Teardown failure and invalidation failure MUST be reported at warning level. Diagnostics MUST describe reclamation as attempted and failed writer release as unconfirmed; logical connection closure MUST NOT be treated as proof that no native cursor remains. Finalization diagnostics MUST report task completion without asserting completion occurred after reclamation.

An observed teardown exception after grace MUST be reported once at warning level with phase, initial bound, elapsed time and the observed error, regardless of whether captured handles are open or closed. A bounded shutdown drain with outstanding cleanup tasks MUST warn with the pending task count and describe connection reclamation and writer-slot release as unconfirmed.

#### Scenario: Native worker completes while loop callbacks are delayed

- **GIVEN** native file-backed SQLite rollback or close completes while the event loop is blocked across the initial bound
- **WHEN** grace observes successful task completion after loop resumption
- **THEN** no fence, interruption, invalidation or deferred cleanup is applied
- **AND** remaining teardown runs and an independent writer can commit without the abandoned write

#### Scenario: Failure, cancellation or pending teardown retains cleanup ownership

- **WHEN** teardown fails, is cancelled or remains pending after grace
- **THEN** the session is fenced and captured open connections receive reclamation attempts
- **AND** original teardown and follow-up close retain the existing cleanup-task registry and bounded shutdown drain

#### Scenario: Failed teardown has already closed its captured handle

- **WHEN** teardown fails after closing a captured connection
- **THEN** the closed handle is skipped, the observed failure is reported and cleanup ownership remains
- **AND** the closed handle does not establish native writer release

#### Scenario: Invalidation fails

- **WHEN** invalidation of a captured open connection raises
- **THEN** the failure is reported at warning level with writer-slot release unconfirmed
- **AND** the original teardown remains owned

#### Scenario: Shutdown follows refused invalidation with a retained writer

- **GIVEN** driver rollback remains pending and captured-connection invalidation fails
- **WHEN** the bounded shutdown drain expires while an independent writer is still refused with database is locked
- **THEN** the warning names the outstanding task count and reports reclamation and writer-slot release as unconfirmed
- **AND** original and follow-up cleanup retain ownership and permit the peer to commit after rollback is released

#### Scenario: Grace observes an exception with an open captured handle

- **GIVEN** a rollback exception is released when the grace observer begins and the captured handle is open
- **WHEN** grace observes the failed teardown
- **THEN** the observed error is reported once at warning level with phase, bound and elapsed time
- **AND** fencing, reclamation attempts and owned follow-up cleanup still run
