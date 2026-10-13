# Enforce GLM model-source concurrency

## Why

The existing request paths sharing a Z.AI credential can exceed the operator's temporary caps. T3 headroom counts and per-task semaphores do not admit physical requests across processes.

## What Changes

At the existing model-source forwarding boundary, enforce at most two simultaneous `glm-5.3-flashx` and five `glm-5.3-flash` physical requests per Z.AI credential, shared by local workers using the same data directory. Hold admission through response/stream cleanup, with bounded wait and an honest local refusal. Capture only allowlisted safe status/model/rate fields for naturally occurring requests.

## Impact

No router, scheduler, inference probe, account change or direct-client routing change. Direct Hermes, T3 ACP and Codex clients remain uncovered until their supported routing is integrated; source proof cannot establish fleet enforcement.
