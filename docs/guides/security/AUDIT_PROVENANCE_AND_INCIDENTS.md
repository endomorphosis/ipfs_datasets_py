# Audit, provenance, and incident evidence

| Field | Value |
| --- | --- |
| Interface | `AuditIncidentGuide@1` |
| Task | `IPFSDOC-061` |
| Status | `canonical` |
| Owner | security; architecture; operators; audit maintainers |
| Source of truth | `ipfs_datasets_py/audit/` (`audit_logger.py`, `handlers.py`, `audit_provenance_integration.py`, `provenance_consumer.py`, `security_provenance_integration.py`, `compliance.py`, `adaptive_security.py`, `intrusion.py`, `audit_reporting.py`); `ipfs_datasets_py/analytics/data_provenance.py` (+ enhanced); MCP `policy_audit_log.py` / event DAG ([AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md)); wallet hash-chain audit (`ipfs_datasets_py/wallet/audit.py`); [ADR-001](../../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-003](../../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Audience | security reviewer, operator/SRE, compliance, developer, agent |
| Related | [THREAT_MODEL.md](THREAT_MODEL.md), [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md), [audit_logging.md](audit_logging.md), [audit_reporting.md](audit_reporting.md), [WALLET_TRUST_AND_PRIVACY.md](../../architecture/WALLET_TRUST_AND_PRIVACY.md) |
| Review cadence | after audit schema, retention policy, disclosure route, or provenance export changes |

> **Hard rules**
>
> 1. **Audit records are correlation evidence**, not authorization, proof of
>    semantic correctness, or legal compliance certificates.
> 2. **Provenance records lineage** (how data was produced). They do not replace
>    CIDs for content identity ([ADR-001](../../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).
> 3. **Incident packages must be redacted** before any public, third-party, or
>    ticket-system disclosure. Never paste real secrets, private keys, raw PII,
>    or unrestricted wallet DEKs into issues or chat.
> 4. **Fail-closed trust**: missing audit or provenance never becomes silent
>    “green” or silent allow ([ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).
> 5. **Visibility ≠ admission**: a green metric, span, or audit “allow” line is
>    not a fresh grant of capability.

---

## 1. Purpose

This guide is the **operational contract** for:

1. **Audit ↔ provenance correlation** — how events, lineage graphs, receipts,
   and content digests join without collapsing authority layers.
2. **Retention, redaction, and export** — what may leave the control plane and
   in what sanitized form.
3. **Incident evidence packaging** — what to collect, preserve, and withhold.
4. **Responsible disclosure** — internal escalation and external reporting routes.

It complements the system [THREAT_MODEL.md](THREAT_MODEL.md) (boundaries) and
[SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md) (credential lifecycle).
Wallet-specific UCAN, multisig, encryption, and public-export sanitation live in
[WALLET_TRUST_AND_PRIVACY.md](../../architecture/WALLET_TRUST_AND_PRIVACY.md).

---

## 2. Audience and when to use this guide

| Audience | Use |
| --- | --- |
| **Operator / SRE** | Configure handlers, retention, and export sinks; run incident collect |
| **Security / compliance** | Correlate who/what/when with lineage; produce redacted reports |
| **Developer / agent** | Attach audit + provenance IDs without inventing authority |
| **Incident responder** | Build an evidence pack without re-leaking secrets |

---

## 3. Mental model: five kinds of truth

Do not collapse these fields. Agents and operators routinely confuse them in
logs; this guide forbids that collapse.

| Kind | Answers | Typical artifact | Is **not** |
| --- | --- | --- | --- |
| **Content identity** | What are the bytes? | CID / multihash under a codec | Location, allow, proof |
| **Provenance / lineage** | How was this produced? | `ProvenanceRecord`, lineage graph, IPLD provenance | Authorization or sat proof |
| **Audit event** | Who did what, when, under what decision context? | `AuditEvent`, wallet hash-chain event, policy audit log | Fresh capability grant |
| **Receipt** | Did a process complete under stated I/O? | Policy / MCP / wallet grant receipt | Content equality or new allow |
| **Authorization** | May this actor act now? | UCAN grant, policy decision, multisig approval | Proven by CID or audit row alone |

```text
  Source bytes ──CID──► Content identity
       │
       ▼
  Transform / merge / query ──► Provenance lineage (references CIDs)
       │
       ▼
  Operator / tool / grant action ──► Audit event (who, action, decision, ids)
       │
       ├── optional Policy/MCP receipt CIDs (correlation)
       └── optional wallet grant_id / approval_id (correlation)

  Monitoring / metrics observe the above — they never authorize.
```

**Core inequalities (repeatable):**

```text
  audit "allow"     ≠  live capability still valid
  provenance edge   ≠  cryptographic proof of claim
  receipt CID       ≠  legal compliance
  export package    ≠  full forensic image
  redacted view     ≠  absence of residual PII risk
```

---

## 4. Package surfaces that participate

### 4.1 Library audit subsystem (`ipfs_datasets_py.audit`)

| Component | Role |
| --- | --- |
| `AuditLogger` | Singleton event bus: level, category, action, resource, user, details |
| `AuditEvent` | Structured record (timestamp, status, source_ip, details, …) |
| Handlers | File, JSON, metrics, remote sinks (`handlers.py`) |
| `AuditMetricsAggregator` / visualization | Aggregate and chart events |
| `AuditReporting` | Compliance-oriented report generation |
| `IntrusionDetection` | Heuristics (e.g. bulk export/download) |
| `AdaptiveSecurity` | Automated response + incident-style escalation hooks |
| `ComplianceStandard` / requirements | Map events to control frameworks |

### 4.2 Provenance domain (`analytics.data_provenance`)

| Component | Role |
| --- | --- |
| `ProvenanceManager` | Record sources, transformations, merges, queries, checkpoints |
| Lineage APIs | `get_data_lineage`, export/import JSON/dict |
| Enhanced / IPLD paths | Optional content-addressed provenance storage and verification |
| `generate_audit_report` | Text/JSON/HTML/Markdown reports from lineage |

### 4.3 Correlation integrators

| Component | Role |
| --- | --- |
| `audit_provenance_integration.AuditProvenanceDashboard` | Unified audit + lineage (+ optional query metrics) views |
| `security_provenance_integration.SecurityProvenanceIntegrator` | Access control + lineage integrity + secure transformations |
| `provenance_consumer` | Query/export consumer with access-aware packaging |

### 4.4 MCP / policy path (correlation only)

Intent → decision → receipt → EventDAG nodes and `PolicyAuditLog` entries. See
[AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md).
Those CIDs **correlate** pipeline history; they do not replace wallet grants or
library audit handlers.

### 4.5 Wallet hash-chain audit

`ipfs_datasets_py.wallet.audit.append_audit_event` builds an **append-only
hash chain** per wallet (`hash_prev` / `hash_self` over canonical payload).
Wallet actions (grant, revoke, export, redacted analysis, WorldID bind, …)
emit `AuditEvent` rows with `actor_did`, `action`, `resource`, `decision`,
optional `grant_id`. Treat the chain as **integrity-friendly correlation**
inside the wallet control plane—not as a global compliance ledger by itself.

---

## 5. Audit ↔ provenance correlation

### 5.1 Correlation keys (join protocol)

When packaging evidence, prefer **stable ids** over free-text messages.

| Key class | Examples | Joins |
| --- | --- | --- |
| **Entity / resource** | `resource_id`, `data_id`, record id, dataset id | Audit event ↔ provenance node |
| **Content digests** | CID, `sha256`, ciphertext hash | Integrity of bytes referenced by lineage |
| **Pipeline artifacts** | `intent_cid`, `decision_cid`, `receipt_cid`, `output_cid` | MCP event DAG ↔ policy audit |
| **Capability** | `grant_id`, `invocation_id`, `approval_id` | Wallet audit ↔ UCAN lifecycle |
| **Request** | `request_id`, `correlation_id`, `event_id` | Logs, OTel, metrics bridge |
| **Actor** | `user`, `actor_did`, `source_ip` (careful with PII) | Attribution |

**Practice:** every high-risk mutation should log **both** an audit action and a
provenance transformation (or an explicit “no lineage change” note). Correlation
is successful when a reviewer can walk:

```text
  actor_did / user
       → audit event_id (decision, timestamp)
       → resource_id / record_id
       → provenance lineage (parents, transform type)
       → input/output CIDs or ciphertext hashes
       → optional grant_id / receipt_cid
```

### 5.2 What correlation is for

- **Forensic reconstruction**: what changed, from which parents, by whom.
- **Access reviews**: who read/exported sensitive resources.
- **Integrity checks**: lineage still points at digests that verify.
- **Incident scoping**: blast radius via shared parent CIDs / shared grants.

### 5.3 What correlation is not for

- Replaying a past audit “allow” as permission for a new call.
- Treating a complete lineage graph as a mathematical proof.
- Using monitoring dashboards as the sole control for production admission.

### 5.4 Integrity expectations

| Check | Meaning |
| --- | --- |
| Provenance integrity verify | Lineage records / optional crypto verification still valid |
| CID / hash recompute | Stored digests match canonical bytes under the declared profile |
| Wallet hash-chain walk | Each event’s `hash_self` matches canonical payload; `hash_prev` links |
| Grant status at time of export | Export evidence should note whether grants were later revoked |
| Replica health (wallet storage) | Encrypted blob sha256 matches on local/IPFS/S3/Filecoin mirrors |

If verification fails, **fail closed** for trust claims: mark evidence
`integrity_unknown` or `tamper_suspected`; do not silently drop the failure.

---

## 6. Retention

### 6.1 Principles

1. **Define retention by data class**, not by a single global “forever” timer.
2. **Security-relevant audit** generally retains longer than debug telemetry.
3. **PII and secrets** should be minimized at write time and redacted on export;
   retention of raw secrets is an incident, not a feature.
4. **Legal holds** (if any) suspend normal deletion—document the hold owner and
   id outside this repo when applicable.
5. **Wallet encrypted blobs** may outlive metadata if replication is multi-backend;
   deletion/revocation plans must cover **all mirrors** (local, IPFS pin, S3,
   Filecoin).

### 6.2 Suggested default classes (operators must instantiate)

| Class | Examples | Suggested default posture |
| --- | --- | --- |
| **Security audit (high)** | Authz deny/allow for sensitive ops, grant revoke, emergency revoke, intrusion hits | Longer retention; append-only preferred; restricted access |
| **Operational audit (medium)** | Dataset transforms, query, config changes | Medium retention aligned with ops SLA |
| **Debug / verbose** | DEBUG-level noise, request traces with large payloads | Short retention; sample; never default production |
| **Provenance lineage** | Source/transform/merge graphs for regulated datasets | Match dataset regulatory class; exportable under access control |
| **Metrics / Prometheus** | Counters, latencies | Short–medium; no secrets in labels |
| **Incident evidence pack** | Sealed zip/JSON of redacted events + hashes | Hold for investigation + postmortem window, then archive or destroy per policy |
| **Wallet export bundles** | Encrypted descriptors + key wraps to audience | Treat as sensitive; revoke wraps/grants on compromise |

Adaptive security responses may set short-lived parameter windows (e.g.
elevated logging for N days). Those windows are **detection aids**, not a
substitute for a formal retention schedule.

### 6.3 Deletion and tombstones

- Prefer **status transitions** (`revoked`, `deleted`, `expired`) that remain
  auditable over silent overwrite of history.
- When hard-deleting encrypted blobs, record a **deletion audit event** with
  resource ids and digests—not plaintext content.
- Cascade awareness: revoking a wallet grant should revoke descendant grants and
  related key wraps (see wallet service `revoke_grant` / `emergency_revoke`).

---

## 7. Redaction

### 7.1 Where redaction applies

| Surface | Expectation |
| --- | --- |
| Application logs / audit `details` | No raw secrets; minimize PII; prefer ids and counts |
| MCP tool results / public views | Redacted authorization and proof views where implemented |
| Wallet analysis / GraphRAG | Pattern redaction + `redacted_derived_only` / `redacted_graphrag` policies |
| Export bundles (public proof fields) | Sanitized statement / public_inputs / metadata only |
| Incident tickets and chat | Redacted pack only; secrets via vault reference |
| Compliance reports | Aggregates and ids; sample events must be scrubbed |

### 7.2 Redaction is incomplete by nature

Wallet `_redact_text` uses **pattern-based** substitution (email, phone, SSN-like
tokens, etc.). It is a **control**, not a guarantee of complete PII discovery.
Document residual risk: free-text secrets, novel identifiers, images/OCR, and
model-side retention outside the package.

### 7.3 Safe detail fields for audit

Prefer:

- ids (`event_id`, `grant_id`, `record_id`, CID prefixes if needed)
- enums / booleans / counts (`redaction_counts`, `decision`, status)
- hashes (`bundle_hash`, `ciphertext_hash`, receipt digests)
- non-sensitive configuration flags

Avoid:

- plaintext documents, location lat/lon, DEKs, private keys, full tokens
- entire request bodies that may contain credentials
- unredacted model prompts/completions with user data

### 7.4 Operator checklist before any export leaves the trust boundary

1. Strip env dumps and `.env` contents.
2. Replace secrets with `$ENV_NAME` or `<REDACTED>`.
3. Confirm wallet export is **encrypted-descriptor** form, not plaintext backup.
4. Confirm proof fields used `_public_export_*` sanitation paths.
5. Confirm no private WorldID nullifier material is included (refs only).
6. Confirm SIEM/ticket attachments are the redacted pack, not full disk images
   unless under a sealed legal process.

---

## 8. Export

### 8.1 Export kinds

| Kind | Source APIs (indicative) | Authority |
| --- | --- | --- |
| **Audit report** | `audit_reporting` generators; metrics export | Operational / compliance narrative |
| **Provenance export** | `ProvenanceManager.export_provenance_to_*`, `provenance_consumer.export_provenance` | Lineage graph package |
| **Integrated dashboard export** | `AuditProvenanceDashboard` visualizations / reports | Correlated view—not a legal seal |
| **MCP event DAG / receipts** | EventDAG walk, receipt CIDs | Pipeline correlation |
| **Wallet encrypted export** | `create_export_bundle`, import/verify helpers | Capability-bound sharing |
| **Wallet snapshot / analytics ledger** | Snapshot and ledger envelopes with verification | Integrity-checked control-plane state |

### 8.2 Export requirements

Every export that leaves a controlled system should carry:

1. **Format / schema id** (e.g. `wallet_export_v1`, report type).
2. **Time range and generator identity**.
3. **Integrity digests** (`bundle_hash`, content hashes) where implemented.
4. **Redaction level** declared (`full_internal`, `redacted_public`, …).
5. **Access label** (who may receive it; grant_id if capability-bound).
6. **Non-claims**: export is not proof of compliance by itself.

### 8.3 Access-controlled provenance export

`provenance_consumer` and security-provenance integration expect **user-scoped**
queries. Do not bypass access checks for convenience in production. If lineage
includes higher-classification parents, either deny, redact edges, or require
elevated approval—document which path the deployment uses.

### 8.4 Wallet export (summary)

Non-owner export requires an `export/create` grant (and often multisig
approval—see wallet architecture). Bundles include **encrypted storage
references** and **key wraps addressed to the audience**, not server-held
plaintext. Public proof sections are sanitized. Import validates hash and schema
and does **not** imply local plaintext availability of blobs.

---

## 9. Incident evidence lifecycle

### 9.1 Incident classes (non-exhaustive)

| Class | Examples |
| --- | --- |
| **Credential exposure** | Secret in logs, leaked JWT, vault file exfil |
| **Unauthorized access / grant abuse** | Stolen UCAN, missing revocation, multisig bypass attempt |
| **Data exfiltration** | Bulk export/download heuristics from intrusion module |
| **Integrity failure** | Provenance chain break, CID mismatch, wallet hash-chain gap, replica hash fail |
| **Policy / pipeline bypass** | Soft-skip of gates, simulated proof treated as production ZKP |
| **Supply chain / prover compromise** | Malicious binary, poisoned dependency |
| **Privacy incident** | PII in public metrics, WorldID nullifier linkage, unredacted GraphRAG leak |

### 9.2 Detection inputs

- Audit categories/levels and intrusion rules (export volume, failed auth).
- Adaptive security responses and escalations (`incident_id` style hooks).
- MCP deny/allow audit + health degradation (context only).
- Wallet audit chain anomalies (unexpected `emergency_revoke`, mass grant).
- Storage health reports (failed replicas, repair events).
- External reports (user, researcher, partner).

### 9.3 Preserve (first hour)

1. **Freeze mutation** of relevant configs where safe (do not destroy evidence).
2. **Capture clocks**: UTC timestamps; note clock skew if known.
3. **Snapshot identifiers**: affected wallet_ids, record_ids, grant_ids, CIDs,
   deployment version, git SHA if available, environment name.
4. **Copy audit windows** covering pre-incident baseline + incident + immediate
   aftermath (prefer raw internal sinks **inside** the trust boundary).
5. **Copy lineage** for affected `data_id`s / records.
6. **Record grant status** and revocation times.
7. **Do not** paste secrets into tickets; store vault references only.

### 9.4 Evidence pack structure (recommended)

```text
incident-<id>/
  README.md                 # timeline summary (redacted)
  meta.json                 # ids, env, versions, collectors
  audit/                    # filtered audit JSON (internal)
  provenance/               # lineage export for affected entities
  wallet/                   # optional: grant receipts, redacted export hashes
  mcp/                      # optional: intent/decision/receipt CID list
  integrity/                # hash verification results
  redacted/                 # only package safe for wider distribution
  EXCLUSIONS.md             # what was withheld and why
```

`meta.json` should include correlation keys (section 5.1) and explicit
`integrity_status` per artifact class.

### 9.5 Analysis questions

1. What was the **first untrusted input** or compromised principal?
2. Which **capabilities** were valid at time of action vs after revoke?
3. Which **content digests** were read, transformed, or exported?
4. Did any **simulated** proof or degraded feature get treated as authoritative?
5. Are **replicas** consistent (wallet storage, IPFS pins, S3, Filecoin)?
6. What residual risk remains after revoke/rotate/repair?

### 9.6 Containment and recovery (aligned with threat model)

| Step | Action |
| --- | --- |
| **Revoke** | Grants, key wraps, JWTs, vault entries, UCAN audiences |
| **Rotate** | Secrets, DEKs (`rotate_record_key` for wallet records), signing keys |
| **Repair** | Storage replicas from known-good encrypted source; re-pin CIDs |
| **Invalidate** | Tainted indexes, embeddings, derived artifacts built from leak |
| **Re-admit** | Only with fresh policy/proof/authorization—not historical audit allow |
| **Monitor** | Elevated audit for the affected principals and resources |

### 9.7 Post-incident

- Timeline (UTC), root cause, impact scope, customer/user notification decision.
- Control gaps → backlog items (tests, redaction patterns, retention).
- Update threat model residual risks if assumptions changed.
- Destroy or archive evidence packs per retention class.

---

## 10. Disclosure

### 10.1 Internal escalation

1. On-call / security owner for the surface (MCP, wallet, storage, logic).
2. Engineering owner for the code path.
3. Privacy / legal as required by deployment policy (out of band).
4. Leadership for high-severity customer impact.

Use the adaptive security / runbook channels configured for the deployment.
This repository does not host a public PagerDuty routing table.

### 10.2 Responsible disclosure (external)

For **security vulnerabilities** in the software:

1. **Do not** open a public GitHub issue with exploit details or secrets.
2. Report **privately** to project maintainers (security contact listed in
   repository security policy / maintainer docs when present; otherwise contact
   maintainers via the project’s documented private channel).
3. Include: affected version/commit, environment class (dev/staging/prod),
   reproduction **without** live credentials, impact assessment, and whether
   exploitation is known.
4. Allow a reasonable remediation window before public write-ups.
5. Coordinate CVE assignment only through maintainers when applicable.

### 10.3 Public communications

Public statements and status pages should use **redacted** facts:

- classes of data affected (not raw samples)
- time windows
- fixed versions / mitigation steps
- what was **not** affected when known

Never publish private keys, DEKs, WorldID nullifiers, unredacted documents, or
full internal evidence packs.

### 10.4 Regulatory / user notification

Jurisdiction-specific duties (breach notification clocks, DSARs, etc.) are
**deployment policy**. Package controls (audit export, subject-access-oriented
compliance actions in `compliance.py`) support evidence; they do not complete
legal notification by themselves.

---

## 11. Worked correlation example (illustrative)

```text
1. Actor did:key:alice invokes MCP tool "wallet_create_export_bundle"
2. Policy audit: decision_cid D allows (risk/UCAN stages pass)
3. Wallet audit: action=export/create, grant_id=G, bundle_hash=H
4. Provenance (dataset path, if any): export transform links parent data_ids
5. Storage: encrypted payload sha256 S on primary + S3 mirror OK
6. Later: grant G revoked → wallet audit grant/revoke; key wraps status=revoked
7. Incident question: "Did post-revoke export succeed?"
   → search audit after revoke time for export/create with grant_id=G
   → if found, treat as control failure; rotate DEKs for covered records
```

Every step is **correlation**. Step 2’s allow does not authorize step 7.

---

## 12. Operator quick commands (local / offline-friendly)

Illustrative patterns—adapt paths and availability to the deployment.

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.analytics.data_provenance import ProvenanceManager

audit = AuditLogger.get_instance()
# Ensure production handlers (file/JSON with rotation) are registered.

provenance = ProvenanceManager()
# After operations that mutate data:
# provenance.record_source(...) / begin_transformation / end_transformation
lineage = provenance.get_data_lineage("<data_id>")
report = provenance.generate_audit_report(format="json")
```

Wallet chain (in-process service):

```python
from ipfs_datasets_py.wallet import DataWalletService

service = DataWalletService()
# service.list_audit_events(wallet_id)  # or API surface used by deployment
# Verify hash chain offline by recomputing hash_self from canonical payloads.
```

Validation of this guide’s presence (documentation gate):

```bash
test -s docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md
rg -n 'incident|redact|UCAN' docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md
```

---

## 13. Non-goals and residual risks

### Non-goals

- Replacing enterprise SIEM, e-discovery, or legal hold products.
- Guaranteeing complete PII discovery via regex redaction.
- Certifying GDPR/SOC2 compliance solely from generated reports.
- Treating simulated ZKP or stub backends as production cryptographic proof.

### Residual risks

| Risk | Mitigation posture |
| --- | --- |
| Incomplete handler coverage | Explicitly list which surfaces log; close gaps as code changes |
| Clock skew across nodes | Prefer content digests + logical ids; note skew in packs |
| Multi-backend orphan blobs | Inventory mirrors on revoke/delete; storage health reports |
| Agent over-trust of audit allow | Training + ADR-003 layering; fail-closed policy |
| Redaction false negatives | Defense in depth; least-privilege grants; short-lived exports |

---

## 14. Related documentation

| Document | Relationship |
| --- | --- |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Trust boundaries, residual risk catalog |
| [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md) | Injection, rotation, redaction of credentials |
| [audit_logging.md](audit_logging.md) | API-level audit logger usage |
| [audit_reporting.md](audit_reporting.md) | Report formats and generation |
| [security_governance.md](security_governance.md) | Broader governance framework |
| [AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md) | MCP event DAG and metrics non-substitution |
| [WALLET_TRUST_AND_PRIVACY.md](../../architecture/WALLET_TRUST_AND_PRIVACY.md) | Wallet encryption, UCAN, multisig, proofs, export sanitation |
| [ADR-001](../../architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | CID vs provenance authority |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence ranking for docs claims |

---

## 15. Change control

| Change type | Action |
| --- | --- |
| New audit category or required correlation field | Update §5 and tests; bump `Last verified` |
| Retention class change | Update §6 with owner sign-off |
| New export format | Update §8 with schema id and redaction level |
| Disclosure contact change | Update §10 without embedding personal secrets |
| Wallet evidence field change | Coordinate with `WALLET_TRUST_AND_PRIVACY.md` |

---

*Interface: `AuditIncidentGuide@1` · Task: `IPFSDOC-061` · Verified: 2026-08-03*
