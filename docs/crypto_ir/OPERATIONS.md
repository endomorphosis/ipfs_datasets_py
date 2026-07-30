# Crypto IR Operations

Status: normative companion for CRYPTOIR-G610 / CRYPTOIR-035  
Release gate: [`RELEASE_AND_ROLLBACK.md`](RELEASE_AND_ROLLBACK.md)  
Authority baseline: [`AUTHORITY_AND_POLICY.md`](AUTHORITY_AND_POLICY.md)  
Threat model: [`THREAT_MODEL.md`](THREAT_MODEL.md)

This runbook describes how operators run Crypto IR in **observation** and
**shadow** modes, promote one reviewed enforcement class at a time, and recover
from budget, freshness, and gate failures. It is not a legal opinion and does
not authorize signing, custody, or external enforcement filings.

## 1. Operating principles

1. **Observe and shadow first.** No enforcement class may skip those stages.
2. **One class at a time.** Promote only a single reviewed enforcement class
   per change window.
3. **Fail closed.** Missing, stale, unsupported, or errored critical evidence
   cannot produce automated `ALLOW`.
4. **Non-custodial.** Processors and gates never hold keys, accept bare
   approval booleans, or broadcast without a consumed one-use capability.
5. **Preserve audit evidence.** Recovery and rollback never delete receipts.
6. **Bound resources and egress.** Offline suites open no sockets; live
   providers obey byte, time, and rate budgets.

## 2. Day-0 readiness checklist

| Check | Operator action | Pass criteria |
| --- | --- | --- |
| Pins | Confirm pinned baseline in release docs matches reviewed tree | No silent tip drift |
| Offline suite | Run multichain + security gate + preflight contract tests | All green |
| Capability inventory | Inventory sign/broadcast entry points via GuardService | Every path gated |
| Secrets | Confirm no inline keys in config; secret references only | TrustPolicy clean |
| Owners | Security, privacy, compliance/legal, operations, release named | Contacts current |
| Mode | Deploy with `observe` (or `shadow` if observe already stable) | No enforcement |

Recommended offline validation:

```bash
python -m pytest -q \
  ipfs_datasets_py/tests/contract/logic/crypto_ir/test_multichain_conformance.py \
  ipfs_datasets_py/tests/contract/processors/smart_contracts/test_security_gate.py \
  ipfs_datasets_py/tests/contract/processors/wallets/test_transaction_preflight.py
```

## 3. Mode runbooks

### 3.1 Observe

**Purpose.** Ingest and normalize chain observations, artifacts, and list
snapshots. No transaction decisions are consumed by signing systems.

| Control | Setting |
| --- | --- |
| Decision emission | Optional diagnostic only |
| Capability issuance | Disabled for production signers |
| Signing / broadcast | Refused without capability (always) |
| SLOs | Ingest lag, normalization error rate, storage growth |

**Operator steps**

1. Enable adapters for the approved chain families only.
2. Verify completeness receipts report missing coverage explicitly.
3. Monitor resource budgets (CPU, memory, CAS storage, provider bytes).
4. Do not attach preflight outcomes to custody signers.

### 3.2 Shadow

**Purpose.** Emit security and compliance decisions beside existing behavior.
Signing remains unaffected by gate outcomes.

| Control | Setting |
| --- | --- |
| Decision emission | Required; store receipts |
| Capability issuance | May run in dry-run; never consumed by production signers |
| Compare | Shadow verdict vs legacy allow path |
| SLOs | Decision latency, disagreement rate, hard-deny false ALLOW = 0 |

**Operator steps**

1. Confirm observe is stable for the target chain family.
2. Enable shadow decision writers with immutable receipt storage.
3. Alert on any hard-deny fixture or live path that would have `ALLOW`ed a
   prohibited case.
4. Weekly review: false positives, unsupported rates, stale rates.

### 3.3 Review-only

**Purpose.** Holds and review queues consume receipts; automated signing stays
disabled.

| Control | Setting |
| --- | --- |
| Holds | Enabled for `DENY` / `REVIEW` / fail-closed carriers |
| Automated sign | Disabled |
| Human override | Outside this system; never a bare boolean field |

### 3.4 Direct-list enforcement

Enable only after shadow false-positive review and legal-owner approval for the
exact jurisdiction/list policy revision. Exact listed identifier hits hard-deny.
Heuristic association never designates.

### 3.5 Contract enforcement

Enable only for obligation sets with adequate semantic coverage, fresh proof
(or approved lower authority where explicitly allowed), and bound code/proxy/
upgrade/state epochs. Upgrades invalidate prior permission.

### 3.6 Indirect-flow enforcement

Promote one bounded, measured risk policy at a time after
false-positive/negative, mixer/exchange/bridge, and legal review. Graph
distance is never designation authority.

## 4. Gates operators must understand

### TransactionPreflight

- Binds one unsigned intent and one exact serialized candidate.
- Composes declared security and compliance requirement results.
- Issues a request-bound, **one-use** admissibility capability only on current
  `ALLOW`.
- Live-revalidates and atomically consumes the capability at pre-sign and
  pre-broadcast.
- Every non-`ALLOW` outcome blocks automation.

### ContractSafetyGate (security gate)

- Binds exact code/proxy/upgrade/state epochs and a required obligation set.
- Distinguishes proof, static, simulation, monitor, and SAT authorities.
- Disproved, unsupported-required, unknown, stale, unavailable, errored,
  mismatched, or unexecuted analyses block automated use.
- Live epoch upgrades invalidate prior decisions.

### ComplianceGate

- Screens every economically relevant counterparty, not only the displayed
  destination.
- Exact listed matches hard-deny.
- Stale or incomplete list/graph evidence blocks automation.
- License exceptions are scoped and expiry-bound.

## 5. Privacy operations

| Concern | Control |
| --- | --- |
| World ID nullifiers | Store commitments/refs only; never raw nullifiers in logs |
| Addresses | Log digests or redacted forms outside secure audit stores |
| Retention | Receipt digests retained; raw provider payloads per policy |
| Export | No automatic external reporting path in processors |
| Access | Least privilege for audit and review queues |

## 6. Legal and compliance operations

1. Sanctions snapshots are offline-injected and content-addressed.
2. Do not fetch live lists from processor import paths.
3. Jurisdiction and list revision are explicit on every screening receipt.
4. Direct-list and indirect-flow promotions require compliance/legal owner
   approval recorded in the release evidence pack.
5. Screening is not a legal certification or reporting action.

## 7. Resource and egress budgets

| Budget | Offline suite | Live (opt-in) |
| --- | --- | --- |
| Network sockets | Forbidden | Allow-listed providers only |
| Package install | Forbidden at import | Forbidden in gates |
| Proof backends | In-process or approved container | Budgeted wall-clock |
| Graph expansion | Bounded depth/nodes | Same bounds + memory cap |
| Artifact bytes | Fixture-sized | Provider byte limits |

Operators treat any budget breach as a release-gate failure for the affected
class.

## 8. Recovery procedures

### 8.1 Stale critical evidence

1. Identify which binding expired (list, graph, code epoch, capability, policy).
2. Confirm automation already blocks (`STALE` / non-ALLOW).
3. Refresh from the authoritative offline path; rebind digests.
4. Re-run affected conformance cases before leaving shadow.

### 8.2 Provider or capability loss

1. Mark capability unavailable; fail closed for required analyses.
2. Keep observe pipelines if they do not depend on the lost capability.
3. Demote contract enforcement if proofs cannot execute.

### 8.3 Reorg / finality retraction

1. Emit retraction-aware receipts; do not silently drop history.
2. Invalidate capabilities bound to retracted coordinates.
3. Queue review for economically relevant open intents.

### 8.4 Suspected false ALLOW

1. Freeze promotion immediately.
2. Demote the class per [`RELEASE_AND_ROLLBACK.md`](RELEASE_AND_ROLLBACK.md).
3. Preserve full receipt trail; open security + compliance incident.
4. Add a regression fixture before re-entry.

### 8.5 Rollback drill (scheduled)

Follow the RollbackPlan in the release document. Success criteria:

- Demotion completes without deleting receipts.
- Signing remains capability-gated.
- Observe/shadow continue healthy.
- Demotion receipt is audit-durable.

## 9. Monitoring and alerts

| Signal | Severity | Response |
| --- | --- | --- |
| Hard-deny path → would ALLOW | Sev-1 | Immediate demotion + incident |
| Stale-critical → would ALLOW | Sev-1 | Immediate demotion + incident |
| Capability consumption race | Sev-2 | Fail closed; investigate store |
| Resource budget breach | Sev-2 | Pause live providers |
| Unsupported rate spike | Sev-3 | Coverage review |
| Observe lag | Sev-3 | Scale or shed load |

## 10. Escalation and owners

| Role | Escalation topics |
| --- | --- |
| Security | False ALLOW, authority elevation, contract gate defects |
| Privacy | Over-collection, nullifier leakage, retention breaches |
| Compliance / legal | List policy, jurisdiction, license exceptions |
| Operations | Budgets, lag, recovery drills, mode health |
| Release | Pin conflicts, promotion windows, gate sign-off |

## 11. Related evidence

- Multichain conformance: `tests/contract/logic/crypto_ir/test_multichain_conformance.py`
- Security gate: `tests/contract/processors/smart_contracts/test_security_gate.py`
- Preflight: `tests/contract/processors/wallets/test_transaction_preflight.py`
- Release/rollback: [`RELEASE_AND_ROLLBACK.md`](RELEASE_AND_ROLLBACK.md)
