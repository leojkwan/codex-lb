## ADDED Requirements

### Requirement: Account-shared model-source request admission
The model-source forwarding boundary SHALL admit at most two simultaneous glm-5.3-flashx and five simultaneous glm-5.3-flash requests to api.z.ai for one credential across local worker processes using the same data directory. It SHALL wait for at most the existing admission timeout, then refuse without contacting the provider.

#### Scenario: All slots are held
- **WHEN** all slots for a capped model and credential are held
- **THEN** an additional request SHALL wait or refuse locally without a provider attempt

#### Scenario: Stream and error cleanup
- **WHEN** a request fails, is cancelled, completes its stream or explicitly closes it
- **THEN** admission SHALL be released after response cleanup, including streams never iterated

### Requirement: Safe natural-traffic metadata
Admission telemetry SHALL contain only timestamps, random request identity, normalized capped model, admission/release events, actual active count, status and allowlisted numeric or canonical date rate/reset/Retry-After values. It SHALL NOT contain prompts, response bodies, URLs, credentials or unrestricted header values.

#### Scenario: Unsafe response header
- **WHEN** a provider returns credentials or arbitrary text in a header
- **THEN** the capture SHALL exclude the value

### Requirement: Honest coverage
Installation and natural-traffic acceptance SHALL separately identify each integrated consumer and observation start. Direct consumers bypassing model-source forwarding, different data directories, missing telemetry and idle observation windows SHALL NOT establish cross-consumer shaping.

#### Scenario: Direct client remains
- **WHEN** a same-account consumer still calls Z.AI directly
- **THEN** the receipt SHALL identify that consumer as uncovered
