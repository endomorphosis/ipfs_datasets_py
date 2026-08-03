# Wallet trust and privacy architecture

| Field | Value |
| --- | --- |
| Interface | `WalletTrustPrivacyArchitecture@1` |
| Task | `IPFSDOC-061` |
| Status | `canonical` |
| Owner | architecture; wallet; security |
| Source of truth | `ipfs_datasets_py/wallet/` (`service.py`, `crypto.py`, `storage.py`, `ucan.py`, `multisig.py`, `proofs.py`, `privacy.py`, `analytics.py`, `models.py`, `audit.py`, `repository.py`, `api.py`, `cli.py`); MCP tools under `ipfs_datasets_py/mcp_server/tools/wallet_tools/`; tests under `ipfs_datasets_py/tests/wallet/` and unit wallet tests |
| Last verified | 2026-08-03 |
| Audience | architect, security reviewer, developer, agent, operator |
| Related | [AUDIT_PROVENANCE_AND_INCIDENTS.md](../guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md), [THREAT_MODEL.md](../guides/security/THREAT_MODEL.md), [SECRETS_AND_CREDENTIALS.md](../guides/security/SECRETS_AND_CREDENTIALS.md), [ADR-001](decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-003](decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md), MCP [POLICY_AND_AUTHORIZATION.md](mcp/POLICY_AND_AUTHORIZATION.md) |
| Review cadence | after wallet crypto, UCAN profile, proof backend, storage adapter, or public-export sanitation changes |

> **Hard rules**
>
> 1. **Server-side wallet storage holds encrypted bytes**, not user plaintext for
>    record payloads. DEKs are envelope-wrapped to principals.
> 2. **UCAN-style grants authorize actions**; CIDs, proof receipts, and audit rows
>    do not.
> 3. **`is_simulated=True` proofs are development/test receipts**, not production
>    zero-knowledge soundness claims. Deterministic location backends are
>    **integration plumbing**, not ZK circuits.
> 4. **Public export and proof public_inputs are sanitized**. Treat residual
>    pattern-redaction risk as real.
> 5. **Multisig / threshold approval** gates sensitive operations when governance
>    threshold &gt; 1—do not soft-skip.
> 6. **No real secrets, DEKs, or WorldID nullifiers** in documentation examples.

---

## 1. Purpose

Describe the **trust model and privacy architecture** of the canonical data
wallet: encrypted records and envelope keys; UCAN grants, invocations, and
revocation; approval/multisig; local / IPFS / S3 / Filecoin replication;
deterministic versus simulated location proofs; privacy analytics and WorldID
bindings; redacted GraphRAG; public export sanitation; and the **authority of
proof fields**.

This document is architecture-level truth for agents and operators. API field
lists may grow; authority rules here must not be silently weakened.

---

## 2. Package map

```text
ipfs_datasets_py/wallet/
  service.py      # DataWalletService — control plane
  crypto.py       # AES-256-GCM envelope encrypt / key wrap
  storage.py      # Local, IPFS, S3, Filecoin, Replicated stores
  ucan.py         # Grant/invocation checks, UCAN profile adapters
  multisig.py     # Threshold approval policy
  proofs.py       # Proof backends (simulated + deterministic)
  privacy.py      # DP / Laplace noise helpers
  analytics.py    # Consent, nullifiers, aggregate counts
  models.py       # Wallet, Grant, ProofReceipt, WorldIdBinding, …
  audit.py        # Per-wallet hash-chain audit events
  repository.py   # Snapshot / analytics ledger envelopes
  api.py / cli.py # HTTP-shaped and CLI surfaces
```

MCP entrypoints wrap the service (`wallet_create`, `wallet_create_record_grant`,
`wallet_issue_*_invocation`, `wallet_create_export_bundle`,
`wallet_create_redacted_graphrag`, analytics and location-proof tools, …).

---

## 3. Trust boundaries

```text
  ┌──────────────────────────────────────────────────────────┐
  │ UNTRUSTED / OUTSIDE                                       │
  │  MCP clients · peers · third-party analytics consumers    │
  │  public export recipients · WorldID RP callbacks          │
  └────────────────────────────┬─────────────────────────────┘
                               │ capability + authn
  ┌────────────────────────────▼─────────────────────────────┐
  │ WALLET CONTROL PLANE (DataWalletService)                  │
  │  grants · invocations · multisig · audit chain · proofs   │
  │  WorldID bindings (nullifier refs) · analytics consent    │
  └────────────────────────────┬─────────────────────────────┘
                               │ encrypted bytes only
  ┌────────────────────────────▼─────────────────────────────┐
  │ ENCRYPTED BLOB STORES                                     │
  │  memory · local · IPFS · S3 · Filecoin (+ mirrors)        │
  │  verify sha256 on read; repair from any valid replica     │
  └──────────────────────────────────────────────────────────┘
```

| Zone | Trusted for | Not trusted for |
| --- | --- | --- |
| **Owner device / owner DID secret** | Unwrap DEKs addressed to owner; issue grants | Being online forever; malware-free |
| **Controller DIDs / approvers** | Multisig threshold operations | Unilateral sensitive ops when threshold &gt; 1 |
| **Delegate audience DID** | Abilities in active grant + caveats + invocation | Broader resources; post-revoke use; plaintext without wrap |
| **Blob store backends** | Durability of **ciphertext** | Confidentiality of plaintext; authorization logic |
| **Proof backends** | Receipt generation under declared `proof_system` | Elevating simulated → production ZK |
| **Analytics aggregator** | Noisy aggregates under policy | Linking keyed nullifiers without wallet secret |
| **MCP policy layer** | Gate tool dispatch | Replacing wallet grant checks |

---

## 4. Encrypted records and envelope keys

### 4.1 Encryption suite

| Constant | Value |
| --- | --- |
| Payload suite | `AES-256-GCM` (`ENCRYPTION_SUITE`) |
| Local key wrap | `AES-256-GCMKW-local` (`KEY_WRAP_ALGORITHM`) |
| AAD | Canonical JSON bytes of associated data (wallet/record/version context) |
| Integrity | SHA-256 of ciphertext / stored blob (`sha256` on `StorageRef`) |

`encrypt_bytes` / `decrypt_bytes` reject wrong suites and raise
`DecryptionError` on authentication failure (GCM tag).

### 4.2 Envelope model

```text
  plaintext record bytes
        │
        ▼
  random DEK (32 bytes)
        │
        ├── AES-GCM(plaintext, DEK, AAD) ──► encrypted blob ──► StorageRef
        │
        └── wrap_key(DEK, recipient_secret, AAD) ──► KeyWrap
                 for owner and each authorized recipient
```

| Type | Role |
| --- | --- |
| `DataRecord` | Logical record (type, sensitivity, public_descriptor, current version) |
| `DataVersion` | Immutable encrypted version: payload/metadata refs, ciphertext_hash, key_wraps |
| `KeyWrap` | DEK wrapped to `recipient_did`; optional `grant_id`; status active/revoked |
| `DerivedArtifact` | Encrypted derived output (redacted analysis, GraphRAG, …) with `output_policy` |
| `StorageRef` | URI, storage_type, size, sha256, optional mirror refs |

**Authority:** possession of a `StorageRef` or CID-like URI **never** implies
plaintext access. Access requires an **active KeyWrap** (or owner path) plus any
grant/invocation checks for non-owners.

### 4.3 Key lifecycle

| Operation | Effect |
| --- | --- |
| Add document/location/record | New DEK, encrypt, wrap to owner (and later to grantees) |
| Grant with decrypt ability | Additional `KeyWrap` for audience (bounded by grant) |
| `rotate_record_key` | New DEK/version; old wraps invalidated for trust purposes |
| `revoke_grant` / `emergency_revoke` | Grant + descendant grants + related wraps → `revoked` |
| Decrypt | Unwrap DEK for actor; GCM decrypt with matching AAD |

Principal secrets are held in the service session map for unwrap; production
deployments must supply them via secure channels—not logs or fixtures.

### 4.4 Recovery bundles

`WalletRecoveryBundleRecord` stores **encrypted recovery material** with
wrapping method metadata (e.g. passphrase + KDF params) and public metadata
only. The server is not expected to hold recovery plaintext.

---

## 5. UCAN grants, invocations, and revocation

### 5.1 Profile identity

Wallet implements a **wallet-native UCAN-style** capability profile:

| Identifier | Meaning |
| --- | --- |
| `WALLET_UCAN_PROFILE_ID` | `wallet-ucan-v1` |
| `WALLET_UCAN_TOKEN_PREFIX` | `wallet-ucan-v1.` |
| External adapter keys | Optional ucanto/w3up / dag-cbor adapter profile ids for interoperability fixtures |

Conformance fixtures and validators live in `ucan.py`
(`wallet_ucan_conformance_fixture`, `validate_ucan_profile_payload`, …).

### 5.2 Resource URIs

| Helper | Pattern |
| --- | --- |
| `resource_for_wallet` | `wallet://{wallet_id}` |
| `resource_for_record` | `wallet://{wallet_id}/records/{record_id}` |
| `resource_for_location` | `wallet://{wallet_id}/location/{record_id}` |
| `resource_for_export` | `wallet://{wallet_id}/exports` |

Matching supports exact match, `*`, and trailing `/*` prefixes.

### 5.3 Grant object

`Grant` fields: issuer/audience DIDs, `resources`, `abilities`, `caveats`,
`proof_chain`, `expires_at`, `status` (`active` / `revoked` / …).

Common abilities (non-exhaustive; see service and multisig sensitive set):

- `record/decrypt`, `document/decrypt`
- `record/analyze`
- `export/create`
- `wallet/admin`
- location / proof related abilities as issued by the service

### 5.4 Caveats (enforced)

`assert_caveats_allow` / grant checks enforce, among others:

| Caveat | Effect |
| --- | --- |
| `not_before` / `nbf` | Not valid before time |
| `record_ids` / `allowed_record_ids` | Restrict records |
| `data_types` / `allowed_data_types` | Restrict record types |
| `output_types` / `allowed_output_types` | Restrict derived/export output classes |
| `purpose` | Invocation purpose must match when both set |
| `user_presence_required` | Invocation must assert user presence |
| Delegation depth / subset rules | Child profile caveats must not broaden parent grant |

Invocations **cannot** expand grant caveats; they may only further constrain
(or satisfy presence/purpose checks).

### 5.5 Invocations

`WalletInvocation` binds `grant_id`, audience, single `resource`, single
`ability`, caveats, nonce, signature, optional issuer. Service
`verify_invocation` checks:

1. Grant active, unexpired, audience match.
2. Resource and ability covered.
3. Caveats allow the operation (including output types for analysis/export).
4. Signature / principal secret as configured by the service path.
5. Multisig approval when required for the operation class.

### 5.6 Revocation

| API | Scope |
| --- | --- |
| `revoke_grant` | Target grant **and descendants** in the proof chain; related key wraps and grant receipts; approved access requests tied to those grants |
| `emergency_revoke` | Wallet-wide grant set for crisis response (often multisig-gated); audit `wallet/emergency_revoke` |
| Access request revoke | Revokes associated grant then marks request revoked |
| Expiry | `is_expired` on grants, invocations, approvals |

**Post-revoke:** decrypt/export/analyze for that audience must fail closed.
Historical audit rows remain for correlation; they do not re-activate access.

### 5.7 Receipts

`GrantReceipt` is an **owner-facing durable receipt** (hash over grant
parameters). It is evidence of issuance, not a second authorization channel.

---

## 6. Approval and multisig

### 6.1 Governance policy

`normalize_governance_policy` sets:

- `approver_dids` (default: wallet `controller_dids`)
- `threshold` clamped to `[1, len(approvers)]`
- `sensitive_abilities` defaulting to:

```text
record/decrypt, document/decrypt, wallet/admin, export/create
```

Optional `sensitive_operations` and caveats such as `full_wallet` or wildcard
resources also force approval when threshold &gt; 1.

### 6.2 Lifecycle

```text
  create_approval_request  →  status=pending
        │
        ▼
  approve_request (per approver_did) until approved_count >= threshold
        │
        ▼
  status=approved  →  verify_approval on sensitive op
        │
        ├── mismatch operation/resources/abilities/requester → deny
        └── expired → deny
```

`ApprovalRequiredError` is raised when `approval_id` is missing or not fully
approved. **Threshold ≤ 1** disables the multisig gate (single-controller
wallets).

### 6.3 Authority statement

Multisig approval authorizes **proceeding with a matching sensitive operation**
once. It does not:

- replace a UCAN grant for delegates,
- prove document contents,
- or survive grant revocation.

---

## 7. Replication: local, IPFS, S3, Filecoin

### 7.1 Store contract

All backends implement encrypted blob `put` / `get` with **sha256** checks on
read. The wallet **never** sends plaintext to backends—only already-encrypted
bytes.

| Backend | Class | Notes |
| --- | --- | --- |
| Memory / Local | `LocalEncryptedBlobStore` | Content-addressed local/dev; local cache |
| IPFS | `IPFSEncryptedBlobStore` | Encrypted blocks; optional pin |
| S3 | `S3EncryptedBlobStore` | S3-compatible client; metadata marks encrypted |
| Filecoin | `FilecoinEncryptedBlobStore` | Filecoin-capable backend adapter |
| Replicated | `ReplicatedEncryptedBlobStore` | Primary + mirrors; health + repair |

Factory: `create_encrypted_blob_store(config, ipfs_backend=…, s3_client=…, filecoin_backend=…)`.

### 7.2 Config shape

```python
# Primary + mirrors (illustrative)
{
  "primary": {"type": "local", "root": "/data/wallet"},
  "mirrors": [
    {"type": "ipfs", "pin": True},
    {"type": "s3", "bucket": "wallet-blobs", "prefix": "wallet/blobs"},
    {"type": "filecoin"}
  ]
}
```

### 7.3 Integrity and repair

| Report | Role |
| --- | --- |
| `StorageReplicaStatus` | Per-replica ok/error/sha256/repaired |
| `StorageHealthReport` | Payload + metadata replica sets for a version |
| `WalletStorageHealthReport` | Wallet-wide summary |
| Repair | Replicate from any valid encrypted source to failed mirrors |

**Trust:** successful replication proves **ciphertext durability**, not
correctness of grants or proofs. Failed hash mismatch → treat replica as bad;
do not “fix” by ignoring integrity.

### 7.4 Deletion / revoke implications

Revoking access does not automatically purge every remote pin. Operators must
plan:

1. Revoke grants and wraps (logical access).
2. Inventory `StorageRef` mirrors.
3. Unpin/delete according to policy (may be delayed on Filecoin deals).
4. Audit the deletion window.

---

## 8. Location proofs: deterministic versus simulated

### 8.1 Receipt model

`ProofReceipt` fields include: `proof_type`, `statement`, `verifier_id`,
`public_inputs`, `proof_hash`, `witness_record_ids`, **`is_simulated`**,
`proof_system`, `circuit_id`, `verifier_digest`, `verification_status`,
optional `proof_artifact_ref`.

### 8.2 Backends

| Backend | `is_simulated` | `proof_system` | Role |
| --- | --- | --- | --- |
| `SimulatedProofBackend` | **True** | `simulated` | Dev receipts; verifier id `simulated-wallet-zkp-v0.1` |
| `DeterministicLocationRegionProofBackend` | **False** | `deterministic-test-proof` | Integration path for region statements; **not** a ZK circuit |
| `DeterministicLocationDistanceProofBackend` | **False** | `deterministic-test-proof` | Integration path for distance statements; **not** a ZK circuit |

Registry: `ProofBackendRegistry` selects backend by proof type / verifier id.

### 8.3 Authority of proof fields (critical)

| Field / flag | Authority |
| --- | --- |
| `is_simulated=True` | **No production cryptographic soundness.** Safe for UX plumbing and tests only. |
| Deterministic backends (`is_simulated=False`) | Prove the **service ran a deterministic checker** over witness data available to the backend—not ZK privacy against the prover host, and not a third-party audited SNARK. |
| `verification_status="verified"` | Backend-local verify result—not a global trust root. |
| `proof_hash` / `verifier_digest` | Integrity of receipt contents under canonical encoding. |
| `public_inputs` | Only what was published; must stay free of plaintext location when policy says so. |
| `witness_record_ids` | Correlation to encrypted records—not disclosure of coordinates. |
| WorldID receipts | Binding / nullifier-ref evidence under declared verifier—not a wallet admin grant. |

**Forbidden collapses:**

```text
  proof verified     ≠  UCAN allow
  simulated proof    ≠  ZK proof
  deterministic proof ≠  privacy-preserving ZK
  location proof     ≠  authorization to decrypt documents
  CID of receipt     ≠  truth of statement in the physical world
```

Agents and UI must surface `is_simulated` and `proof_system` whenever proofs
are shown.

### 8.4 Location claims

Precise coordinates live in encrypted location records. Proof APIs accept
region/distance **statements** and public inputs while keeping witness handling
inside authorized decrypt paths. Prefer proofs that reveal **membership or
distance predicates**, not raw lat/lon, in public_inputs.

---

## 9. Privacy analytics and WorldID

### 9.1 Analytics templates and consent

| Object | Role |
| --- | --- |
| `AnalyticsTemplate` | Approved study: allowed record types, derived fields, aggregation policy |
| `AnalyticsConsent` | User consent scoped to template; revocable |
| `AnalyticsContribution` | Fields + nullifier + proof_id for one contribution |
| `AggregateResult` | Released counts / noisy counts under policy |

### 9.2 Nullifiers

`contribution_nullifier(wallet_id, template_id, consent_id, wallet_secret=…)`:

- Without secret: stable hash (linkable if wallet_id enumerable).
- With wallet secret: **HMAC** so released ledgers do not trivially map to
  wallet ids.
- Consent id is intentionally **outside** the keyed message so re-consent cannot
  bypass duplicate protection for the same template.

### 9.3 Differential privacy helpers

`AnalyticsPrivacyPolicy` / `noisy_count`:

- `min_cohort_size` gate (default 10)
- Optional Laplace noise with `epsilon` / `sensitivity`
- Optional privacy budget key/limit
- Deterministic noise **only** for reproducible tests (`seed_material`);
  production path uses cryptographically strong randomness

Aggregates that fail cohort thresholds must not release exact re-identifying
counts.

### 9.4 WorldID bindings

`WorldIdBinding` attaches a durable **proof-of-human** style binding:

| Field | Trust meaning |
| --- | --- |
| `nullifier_ref` | Public reference—not raw nullifier material in exports |
| `rp_id`, `action`, `protocol_version`, `environment` | Binding context |
| `verification_status`, `status` | Local binding state |
| `proof_receipt_id` | Linked proof receipt (`world_id_proof_of_human` / idkit v4 system ids) |

Service constants (indicative):

- `WORLD_ID_PROOF_TYPE = "world_id_proof_of_human"`
- `WORLD_ID_PROOF_SYSTEM = "world_id_idkit_v4"`
- `WORLD_ID_VERIFIER_ID = "world_id_developer_portal_v4"`

Private nullifier material is stored in internal maps for dedupe; **public
surfaces must use refs**. WorldID does **not** grant `record/decrypt` or
`export/create`.

---

## 10. Redacted GraphRAG and analysis

### 10.1 Output policies

| Policy | Meaning |
| --- | --- |
| `redacted_derived_only` | Pattern-redacted text + derived facts; no raw PII intent |
| `redacted_graphrag` | Graph built from redacted per-record extractions |
| `encrypted_export_bundle` | Sharing view of ciphertext descriptors |
| `no_plaintext_public_inputs` | Document-profile public inputs stripped to allowlist |

Non-owner analysis requires grant ability `record/analyze` and matching
`output_types` caveats.

### 10.2 Redacted document analysis

`analyze_document_with_redaction`:

1. Authorize (owner or grant).
2. Decrypt under DEK wrap rules.
3. `_redact_text` via `REDACTION_PATTERNS` → `[REDACTED_*]` placeholders.
4. Truncate; derive coarse facts (need categories, contact-redaction flags).
5. Encrypt derived output as `DerivedArtifact`.
6. Audit `record/analyze_redacted` with counts—not plaintext.

### 10.3 Redacted GraphRAG

`create_redacted_graphrag`:

1. Authorize each `record_id`.
2. Extract text (optional OCR) with size caps.
3. Redact per record; count entity types / categories on **redacted** text.
4. Build graph aggregate; encrypt artifact under `redacted_graphrag` policy.
5. Backend id constant: `wallet-local-redacted-graphrag-v1` (local integrator path).

**Residual risk:** OCR/images, novel PII shapes, and model-side retention if
external organizers are enabled. Treat redaction as necessary, not sufficient.

### 10.4 Vector / document profiles

Document vector profiles and related proofs route public_inputs through
`_safe_document_profile_public_inputs` (allowlisted keys only: counts, labels,
redaction_count, privacy_policy, …).

---

## 11. Public export sanitation

### 11.1 Export bundle properties

`create_export_bundle` produces `bundle_type: wallet_export_v1`:

- Wallet descriptor (full for owner; minimized for delegates).
- Records + versions with **only audience key wraps** for non-owners.
- Optional derived artifacts and **sanitized** proofs.
- `bundle_hash` over canonical unsigned content; `bundle_id` derived from hash.
- Audit `export/create` with record ids and hashes—not plaintext.

Import verifies hash + schema and registers **encrypted descriptors only**.

### 11.2 Proof sanitation

`_public_export_proof_receipt` keeps only `PUBLIC_EXPORT_PROOF_KEYS` and runs
sanitizers on `statement`, `public_inputs`, `metadata`, and witness id lists.
Sensitive keys in public_inputs are dropped or scrubbed (implementation filters
on key names / value shapes).

### 11.3 Snapshot and ledger envelopes

`LocalWalletRepository` can verify **snapshot envelopes** and **analytics ledger
envelopes**. Envelope verification failures fail closed (do not load untrusted
state as authoritative).

### 11.4 Sanitation checklist for public or partner release

1. Use export/create grant path—not ad-hoc DB dumps.
2. Confirm non-owner wraps only for intended audience.
3. Confirm proofs passed `_public_export_*`.
4. Confirm no raw WorldID nullifiers.
5. Confirm analytics exports respect cohort + DP policy.
6. Attach `bundle_hash` verification procedure for recipient.
7. Plan revoke: wraps + grant + optional DEK rotate if bundle leaked.

---

## 12. Trust and authority matrix (summary)

| Artifact | Confers |
| --- | --- |
| Encrypted `StorageRef` | Location of ciphertext |
| Active `KeyWrap` + principal secret | Ability to unwrap DEK for that version |
| Active `Grant` + matching `WalletInvocation` | Ability to perform listed abilities on resources under caveats |
| Approved `ApprovalRequest` | Permission to execute one matching sensitive operation |
| Wallet audit event | Append-only history for correlation |
| `GrantReceipt` | Issuance evidence for owner records |
| Simulated `ProofReceipt` | Dev/test placeholder only |
| Deterministic location `ProofReceipt` | Integration-level statement check—not ZK |
| WorldID binding | Uniqueness / humanity binding under RP context |
| Analytics aggregate | Privacy-budgeted cohort statistic |
| MCP policy allow | Tool dispatch admission—still need wallet grant for wallet tools |
| CID of any of the above | Content identity of the artifact bytes only |

---

## 13. Audit integration (wallet)

Per-wallet events via `append_audit_event`:

- Hash-chained (`hash_prev` / `hash_self` over canonical payload).
- Fields: `actor_did`, `action`, `resource`, `decision`, `details`, optional
  `grant_id`.

Typical actions include grant create/revoke, export/create, record analyze
(redacted), world_id_bind, emergency_revoke, device revoke, storage repair.

Correlate with the broader audit/provenance guide:
[AUDIT_PROVENANCE_AND_INCIDENTS.md](../guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md).

---

## 14. Operator and agent guidance

### Do

- Issue least-privilege grants (record ids, output types, short expiry).
- Require multisig for production wallets that control real PII.
- Replicate **ciphertext** only; verify sha256 after failover.
- Label every proof with `is_simulated` and `proof_system` in UX.
- Prefer redacted analysis/GraphRAG for delegates.
- Revoke, then rotate DEKs, on suspected export leak.

### Do not

- Log DEKs, principal secrets, or raw WorldID nullifiers.
- Treat simulated proofs as production ZK.
- Skip invocation verification because “audit said allow yesterday.”
- Put plaintext datasets on IPFS/S3 “for convenience.”
- Broaden caveats in child delegations.
- Assume Filecoin/IPFS deletion is immediate after revoke.

---

## 15. Testing and validation anchors

| Area | Evidence (indicative) |
| --- | --- |
| Canonical imports | `tests/unit/test_wallet_canonical_imports.py` |
| Storage factory | `tests/unit/test_wallet_storage_factory.py` |
| Service / API | `tests/unit/test_data_wallet.py`, `test_wallet_api_adapter.py` |
| UCAN conformance | fixtures/validators in `wallet/ucan.py` + wallet tests |
| MCP tools | `mcp_server/tools/wallet_tools/*` |

Documentation gate for this task:

```bash
test -s docs/architecture/WALLET_TRUST_AND_PRIVACY.md
rg -n 'UCAN|multisig|encrypt|replication|simulated|redact' docs/architecture/WALLET_TRUST_AND_PRIVACY.md
```

---

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [AUDIT_PROVENANCE_AND_INCIDENTS.md](../guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md) | Incident packs, retention, disclosure, correlation |
| [THREAT_MODEL.md](../guides/security/THREAT_MODEL.md) | System threats including wallet residual risk |
| [SECRETS_AND_CREDENTIALS.md](../guides/security/SECRETS_AND_CREDENTIALS.md) | Credential injection and redaction |
| [ADR-001](decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | CID vs provenance vs authz |
| [ADR-003](decisions/ADR-003-LAYERED-AUTHORITY.md) | Layered authority non-collapse |
| [POLICY_AND_AUTHORIZATION.md](mcp/POLICY_AND_AUTHORIZATION.md) | MCP UCAN/policy stages for tool dispatch |
| Wallet tools README | `ipfs_datasets_py/mcp_server/tools/wallet_tools/README.md` |

---

## 17. Change control

| Change | Required doc update |
| --- | --- |
| New encryption suite or wrap algorithm | §4 + threat residual risks |
| New ability or caveat | §5 + multisig sensitive set if needed |
| New storage backend | §7 |
| New proof backend | §8 authority table (`is_simulated`, soundness claim) |
| Public export key allowlist | §11 |
| WorldID protocol version | §9.4 |

---

*Interface: `WalletTrustPrivacyArchitecture@1` · Task: `IPFSDOC-061` · Verified: 2026-08-03*
