## Implementation
- [x] Add cross-process physical-request admission and safe metadata telemetry.
- [x] Integrate chat and Responses non-stream and stream paths with existing cleanup ownership.
- [x] Prove cap, cancellation, failure and stream release using real process locks and fake transports.
- [x] Record exact source/install/live coverage and leave adoption unproved until observed.

## Adoption boundary
Source tests cover one credential and shared data directory only. Multiple keys
for one account, direct Hermes SDK, T3 GLM ACP and codexz clients, embeddings and
audio remain uncovered. Installed 1.24 is unchanged; this source is based on
1.25.0-beta.9. No installation, natural traffic or account-wide acceptance is
established by these completed source tasks.
