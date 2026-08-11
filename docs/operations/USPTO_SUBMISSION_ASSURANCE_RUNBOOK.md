# USPTO Submission Assurance — Operator Runbook

**Task:** `PATLAW-073`  
**Track:** operations / submission assurance  
**Code:** `ipfs_datasets_py.processors.domains.uspto.scheduler`  
**CLI:** `scripts/ops/uspto/status.py`  
**Tests:** `tests/integration/processors/domains/uspto/test_recovery_operations.py`

This runbook is the operator surface for **liveness**, **stall detection**, and
**idempotent recovery** of USPTO application-matter polling and submission
assurance workflows. It does **not** replace the protected
patent-legal-intelligence supervisor launcher (`scripts/ops/patent_legal_intelligence/`).

## Standing rules (fail-closed)

1. **Content-free observability.** Status, alerts, heartbeats, metrics, and
   recovery audit records must never include document bodies, extracted text,
   embeddings, API keys, bearer tokens, cookies, or raw provider payloads.
2. **Evidence is append-only.** Recovery never deletes dead letters, alerts,
   fingerprints, known artifact ids, or prior audit records.
3. **No sign / file / pay.** Operators re-arm polls and rotate **opaque
   credential references** only. Automated filing, payment, or signature is
   out of scope.
4. **Idempotent recovery.** Every recovery run is keyed by `recovery_id` and
   written under the audit directory. Replaying the same id with the same plan
   is a no-op; a conflicting body for the same id is refused.
5. **Private-policy incidents quarantine.** Security / privacy dead letters do
   not re-enter public sinks. Binary content jobs are not auto-replayed from
   policy incidents.

## Operator phases

`scripts/ops/uspto/status.py` classifies a durable scheduler checkpoint into
exactly one dominant phase (priority order):

| Phase | Meaning | Typical signals |
| --- | --- | --- |
| `policy_incident` | Security, privacy, credential-health, or dead-letter review requires a human | Open `credential_health` action; `security_failure` / `parse_failure` dead letter |
| `stalled` | Open work without fresh progress | Running job `updated_at_utc` older than stall threshold; tick + heartbeat both stale while queue non-empty |
| `active_progress` | Work is actively executing | `jobs.running > 0` or `workers_in_use > 0` with fresh ticks |
| `bounded_backoff` | Finite delay after rate-limit, auth, upstream error, or open circuit | Job `state=waiting` with disposition `rate_limited` / `unauthorized` / `upstream_error` / `circuit_open`; circuit state `open` |
| `waiting` | Delayed or gated work; **workers released** | `state=waiting` / `pending` without backoff disposition (e.g. metadata-before-binary gate) |
| `completed_merge` | No open work or incidents; optional merge receipt accepted | All jobs terminal success/cancel; no open actions; optional merge receipt `status=merged` |

### Distinguishing waiting vs bounded backoff vs stalled

| Question | Waiting | Bounded backoff | Stalled |
| --- | --- | --- | --- |
| Are workers held? | No | No | Often yes (running claim) or progress clocks dead |
| Is delay finite and intentional? | Yes (gate / schedule) | Yes (`Retry-After`, exponential cap, circuit recovery) | No — schedule or heartbeat overdue |
| Operator action | Usually none | Wait or rotate credentials (auth) | Investigate process/host; then `safe_resume` |

### Active progress vs completed merge

* **Active progress:** at least one running job or worker slot held; ticks/heartbeats advance.
* **Completed merge:** zero pending/waiting/running jobs, zero open operator actions, and either an empty residual set of dead letters **or** an explicit merge receipt that records acceptance. Prefer a content-free merge receipt JSON (`status: merged`) when integrating with the release gate (`PATLAW-074`).

## Content-free health metrics

Source of truth: `USPTOApplicationScheduler.health()` / checkpoint `progress`,
projected by the status CLI (never re-hydrates document bytes).

| Field group | Examples | Privacy rule |
| --- | --- | --- |
| Identity | `interface`, `schema_version` | Constants only |
| Workers | `workers_in_use`, `workers_available` | Counts |
| Jobs | `jobs_enqueued`, `jobs_running`, `jobs_waiting`, `jobs_completed`, `jobs_dead_lettered` | Counts |
| Circuits | per-service `open` / `closed` / `half_open` | Enum only |
| Liveness | `last_heartbeat_utc`, `last_tick_utc`, `ticks` | Timestamps / counters |
| Changes | `changes_detected`, `alerts_emitted` | Counts |
| Artifacts | `known_artifact_count` | Count of opaque ids only |

CLI:

```bash
# Machine-readable status (default command)
python scripts/ops/uspto/status.py \
  --checkpoint-dir "$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/scheduler" \
  --json

# Human summary
python scripts/ops/uspto/status.py --checkpoint-dir /path/to/ckpt --text

# Phase taxonomy
python scripts/ops/uspto/status.py phases
```

Default checkpoint directory (when unset):

`$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/scheduler`
(or `~/.local/state/...` when `XDG_STATE_HOME` is unset).

## Recovery operations

All recoveries are invoked as:

```bash
python scripts/ops/uspto/status.py recover \
  --checkpoint-dir /path/to/ckpt \
  --audit-dir /path/to/audit \
  --kind <kind> \
  [--job-id ...] [--dead-letter-id ...] \
  [--new-credential-ref-id opaque-ref] \
  [--recovery-id stable-id] \
  [--dry-run]
```

Audit records land in `--audit-dir` (default under
`.../uspto_submission_assurance/recovery_audit`) as `rec_*.json`.

| Kind | When | Operator steps | Must not |
| --- | --- | --- | --- |
| `auth_expiry` | 401/403 → `credential_health` | Rotate secret **outside** this tool; pass new **opaque** `credential_ref_id`; run recovery to resolve action and re-arm jobs | Put API keys in CLI args, status, or audit |
| `rate_backoff` | 429 / `rate_limited` | Confirm `Retry-After` honored; wait; do not force-skip | Delete waiting jobs or alerts |
| `outage` | Repeated 5xx / circuit open | Confirm upstream healthy; optionally re-arm a job after outage clears | Clear circuit evidence or dead letters |
| `schema_drift` | `parse_failure` dead letter | Fix parser/ruleset offline; replay via **new** job id; keep DL | Mutate or delete the dead-letter record |
| `corrupt_document` | parse/security DL on binary | Quarantine artifact in private store; optional metadata-only replay | Re-publish corrupt bytes to public sinks |
| `private_policy_incident` | security/privacy incident | Acknowledge actions; keep quarantine; engage privacy review | Auto-replay `document_bytes` jobs |
| `dead_letter` | Any reviewable DL | Review reason codes; enqueue replay job clone | Delete DL / alert history |
| `stale_checkpoint` | Unreadable or suspect state | Validate schema; reload from durable path; compare evidence fingerprint | Hand-edit away evidence arrays |
| `replay` | Safe re-drive of non-terminal jobs | Promote to `pending` without clearing `alert_dedupe_index` or artifact ids | Re-emit duplicate alerts for same dedupe key |
| `key_rotation` | Credential rotation window | Supply new opaque ref; resolve open credential actions | Embed bearer tokens or JWT material |
| `safe_resume` | Process crash / host restart | Release stuck `running` claims; promote due waiters | Drop fingerprints or known artifact ids |

### Idempotency and audit

* Choose a stable `--recovery-id` (for example `rec_auth_2026-08-03_app1777`).
* First successful apply writes `audit_dir/<recovery_id>.json`.
* Second apply with the **same** id and body is a no-op at the audit layer;
  checkpoint mutations that requeue an already-present replay job id are also
  no-ops.
* Conflicting body for an existing `recovery_id` **fails closed**.

### Evidence preservation check

Every recovery computes an evidence fingerprint over:

* dead-letter ids
* alert ids
* fingerprints map
* known artifact ids

If a plan would remove any prior id, recovery raises and writes nothing.

## Incident playbooks

### 1. Auth expiry (401 / 403)

**Symptoms:** `phase=policy_incident` or `bounded_backoff`; open
`credential_health` action; job disposition `unauthorized` / `forbidden`.

**Recovery:**

1. `python scripts/ops/uspto/status.py --checkpoint-dir … --text`
2. Rotate the secret in the credentials vault (never in git or shell history).
3. Record the new **opaque** credential reference id.
4. `recover --kind auth_expiry --new-credential-ref-id <ref> --job-id <id> --recovery-id …`
5. Or `recover --kind key_rotation --new-credential-ref-id <ref> …` when many jobs share the ref.
6. Confirm phase leaves `policy_incident` after actions resolve; workers remain free while waiting.

### 2. Rate backoff (429)

**Symptoms:** `phase=bounded_backoff`; disposition `rate_limited`; alert
`rate_limit`.

**Recovery:**

1. Do **not** force immediate retry unless policy explicitly allows (default: wait).
2. `recover --kind rate_backoff --dry-run` to audit observation.
3. After the bounded delay elapses, the scheduler promotes waiters on the next tick.
4. If stalls persist past SLO, treat as `outage` / capacity issue — not as a
   reason to delete queue state.

### 3. Upstream outage / open circuit

**Symptoms:** circuit state `open`; disposition `upstream_error` or
`circuit_open`; action `circuit_recovery`.

**Recovery:**

1. Confirm USPTO ODP / service health from operator channels (not by scraping).
2. Wait for `circuit_recovery_seconds` half-open probe via normal ticks.
3. After external confirmation, `recover --kind outage --job-id …` to re-arm a specific waiter.
4. Keep alerts; do not reset failure counts by hand-editing the checkpoint.

### 4. Schema drift

**Symptoms:** dead letter `reason=parse_failure`; error code `parse_failure` /
`schema_invalid`.

**Recovery:**

1. Preserve the dead letter and job snapshot **as stored** (already redacted).
2. Fix parser/contracts in a normal code change (out of band).
3. `recover --kind schema_drift --dead-letter-id …` creates a **new** replay job
   id; original DL remains.
4. Replay is network-free when wired to fixture pollers in tests; production
   pollers use the same job fields without re-injecting bodies into status.

### 5. Corrupt document

**Symptoms:** parse or security dead letter on `content_kind=binary`.

**Recovery:**

1. Treat artifact as untrusted; verify private-store quarantine.
2. `recover --kind corrupt_document --dead-letter-id …` only after a clean
   replacement artifact is available under a new artifact id.
3. Never delete the failed artifact id from `known_artifact_ids` (dedupe /
   audit).

### 6. Private-policy incident

**Symptoms:** `phase=policy_incident`; security dead letter; privacy sink denial
in assurance tests.

**Recovery:**

1. `recover --kind private_policy_incident` — acknowledges without requeue of
   document bytes.
2. Engage privacy review; export remains denied by default.
3. Only after classification is known-public may a **new** metadata job be
   enqueued by normal operator tools — still without deleting the incident.

### 7. Dead letter review

**Symptoms:** open `review_dead_letter` action; `jobs_dead_lettered > 0`.

**Recovery:**

1. Read reason codes only (`parse_failure`, `security_failure`,
   `permanent_client_error`, `operator`).
2. `recover --kind dead_letter --dead-letter-id …` to enqueue a replay clone.
3. Confirm audit `evidence_preserved=true`.

### 8. Stale checkpoint

**Symptoms:** missing heartbeat, unreadable JSON, or process restart mid-tick.

**Recovery:**

1. `recover --kind stale_checkpoint` validates schema and records reload intent.
2. Prefer `USPTOApplicationScheduler.reload()` / process restart so in-memory
   worker holds are dropped (running claims do not survive crash).
3. Follow with `safe_resume` if any `running` rows remain in the durable file.

### 9. Safe resumption after crash

**Symptoms:** process gone; checkpoint shows `running` jobs; workers should be free.

**Recovery:**

1. `recover --kind safe_resume` releases `running` → `pending` and promotes due waiters.
2. Start scheduler workers; `tick` / `run_until_idle` resumes without duplicate
   artifact admission when `known_artifact_ids` is intact.
3. Heartbeat alerts may re-fire (`force`); change alerts remain deduped.

### 10. Key rotation

**Symptoms:** planned rotation or post-auth incident.

**Recovery:**

1. Install new secret in the vault under a new opaque ref id.
2. `recover --kind key_rotation --new-credential-ref-id <new-ref>`
3. Reject ref ids that look like bearer tokens / JWTs / `sk-` secrets.
4. Old ref may remain on historical actions for audit; open credential actions resolve.

### 11. Deterministic offline replay

**Symptoms:** need to re-drive analysis without network (release / e2e track).

**Recovery:**

1. Use immutable fixture receipts (see `PATLAW-072` when present).
2. `recover --kind replay --job-id …` re-arms non-terminal jobs.
3. Do not clear `alert_dedupe_index` or `known_artifact_ids`.
4. Status output must still pass content-free checks against fixture bodies.

## Stall detection thresholds

| Parameter | Default | CLI flag |
| --- | --- | --- |
| Running / open-work stall | 600s | `--stall-seconds` |
| Heartbeat+tick stale with open work | 300s | `--heartbeat-stale-seconds` |

Tune per environment; do not page on document content. Prefer counters, ages,
circuit state, and phase.

## Privacy and logging allowlist

**Allowed:** job id, application number, matter id, service name, content kind,
status codes, disposition enums, reason codes, opaque credential ref ids,
fingerprint digests, artifact id digests, timestamps, counters.

**Forbidden:** document bytes/text, embeddings, authorization headers, API keys,
session cookies, full provider JSON bodies, private classification payloads in
telemetry.

Use `assert_content_free` (status module) or equivalent in CI when extending
operator projections.

## Validation

```bash
python -m pytest tests/integration/processors/domains/uspto/test_recovery_operations.py -q
python scripts/ops/uspto/status.py --help >/dev/null
```

Related:

* Scheduler contracts: `ipfs_datasets_py/processors/domains/uspto/scheduler.py` (`PATLAW-062`)
* Privacy sinks / assurance: `privacy.py`, `privacy_sinks.py` (`PATLAW-071`)
* Release gate (downstream): `PATLAW-074`
