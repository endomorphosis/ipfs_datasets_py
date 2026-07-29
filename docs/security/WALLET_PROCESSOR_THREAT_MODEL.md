# Wallet Processor Threat Model (WALPROC-G630)

Date: 2026-07-29  
Scope: Bitcoin, XRPL, Xaman, Ethereum, Solana, World Chain, and World ID processor surfaces in `ipfs_datasets_py`  
Related repairs: WALPROC-049, WALPROC-060, WALPROC-061, WALPROC-062, WALPROC-063  
Evidence tests: `ipfs_datasets_py/tests/security/test_wallet_processor_secrets.py`, `ipfs_datasets_py/tests/security/test_wallet_processor_bounds.py`

## Mission boundary

Wallet processors ingest, normalize, checkpoint, and export **read-only** ledger and identity evidence. They must never accept custody of seeds, private keys, or transaction-signing authority. Signing, approval, submission, and broadcast remain **explicitly denied future capabilities** on every processor and provider surface.

Public ledger data is treated as **potentially personal**. Correlation, identity clustering, free-form memo/instruction retention, and raw payload custody are restricted by default and require explicit, bounded opt-in.

## Assets

| Asset | Sensitivity | Notes |
| --- | --- | --- |
| Provider credentials / secret references | Critical | Held only as opaque references; resolved at runtime by an injected lookup |
| World ID RP signing material and nullifier HMAC keys | Critical | Never appear in public config, durable dicts, logs, or errors |
| Raw nullifiers, proofs, JWTs, signatures | Critical | Redacted or commitment-wrapped before public export |
| Full provider endpoint URLs | High | Public views expose fingerprints only |
| Free-form XRPL memos / Xaman instructions / calldata | High | Default omit/redact; content retention is opt-in and size-bounded |
| Raw provider payloads | High | Omitted by default; custody stores enforce object/total/count limits |
| Canonical records, checkpoints, manifests, receipts | Medium | Must reject nested secret-shaped keys and concrete secret values |
| Public addresses, tx digests, amounts, finality | Low–Medium | Deterministic and required for export integrity; still privacy-sensitive in aggregate |

## Trust boundaries

1. **Operator / secret manager** — sole authority that materializes credentials. Processors receive `SecretReference` pointers only.
2. **Injected transport / DNS** — untrusted for SSRF, rebinding, redirects, and oversized bodies.
3. **Upstream providers** — may lie, throttle, or embed secrets in error text; exceptions are sanitized.
4. **Export consumers** — receive redacted public projections, never raw secrets or full secret-reference paths.
5. **Future custody extensions** — out of scope; capability flags stay false and public callables must not grow sign/broadcast verbs without a new threat review.

## Threat catalog and controls

### T1 — Secret smuggling through serialization (WP-SEC-001)

**Threat.** Nested secret-shaped fields or concrete secret values enter extensions, checkpoint metadata/cursors, manifest warnings, receipts, or logs.

**Controls.**

- Recursive `ensure_secret_safe` policy on canonical extensions, free-form checkpoint fields, manifests, and receipts (WALPROC-060).
- `SecretValue`, `SecretReference`, `SecretHeaderValue`, and `WorldIdSecretConfig` representations omit values and full reference paths.
- Provider auth accepts secret references only; plaintext credential headers are rejected.

**Tests.** Secret-surface and recursive serialization cases in `test_wallet_processor_secrets.py`.

### T2 — World ID secret-reference and nullifier disclosure (WALPROC-G630-R1 / WP-SEC-001)

**Threat.** `WorldIdSecretConfig` repr/str or public config leaks direct key material, complete secret-manager paths, or raw nullifiers.

**Controls.**

- Dataclass representations report only `configured` / `source` (WALPROC-049).
- Durable/public serialization uses bounded source kinds and opaque reference identifiers.
- Verification results wrap identity material; redactors strip proofs, signatures, JWTs, and nullifiers (WALPROC-063).

**Tests.** World ID config and redaction cases in `test_wallet_processor_secrets.py`.

### T3 — Endpoint and credential leakage in errors (WP-NET-004)

**Threat.** Full URLs, userinfo, query credentials, or upstream exception chains appear in operator-visible errors.

**Controls.**

- `endpoint_fingerprint` and `safe_exception_text` replace endpoints with non-reversible labels.
- `EndpointPolicy` rejects userinfo, fragments, secret-bearing query keys, non-allowlisted hosts, unsafe literal IPs, and non-global DNS answers.
- Upstream causes are not chained into permanent provider errors.

**Tests.** Endpoint policy and exception-safety cases in both security test modules.

### T4 — Unbounded raw payload custody (WP-BOUNDS-002)

**Threat.** Oversized or high-count raw bodies exhaust memory/disk or persist without authorization.

**Controls.**

- Default raw-payload policy omits custody.
- `RawPayloadCustodyLimits` enforce per-object, total-byte, and object-count caps **before** state changes (WALPROC-061).
- Directory stores use restrictive permissions; encrypted mode fails closed without an encryptor.

**Tests.** `test_wallet_processor_bounds.py` store and limit cases.

### T5 — Free-form content retention by default (WP-PRIV-003)

**Threat.** XRPL memos or Xaman custom instructions retain personal free-form content in normal ingest paths.

**Controls.**

- Default privacy policies redact or omit instruction/body content while keeping presence, length, digest, and redaction metadata (WALPROC-062).
- Explicit opt-in policy required for bounded content retention; existing byte/item caps remain.

**Tests.** Xaman/XRPL redaction projections in `test_wallet_processor_secrets.py`.

### T6 — SSRF, decompression bombs, and pagination abuse

**Threat.** Metadata IPs, DNS rebinding, open redirects, oversized/compressed bodies, cursor loops, or unbounded pages.

**Controls.**

- Shared `EndpointPolicy` + bounded transport (timeouts, response/request bytes, page/item/request budgets, range size).
- World ID verification reuses policy-approved HTTPS endpoints and finite attempt budgets (WALPROC-063).

**Tests.** Bounds and DNS cases in `test_wallet_processor_bounds.py`.

### T7 — Future custody / signing capability creep

**Threat.** Sign, approve, submit, or broadcast methods appear on processor/provider public surfaces.

**Controls.**

- Capability metadata marks supports_sign / supports_submit / supports_broadcast / supports_approve as false where applicable.
- Xaman `assert_read_only_surface` guards denied verb names.
- API layer documents no signing or broadcast verbs.

**Tests.** Capability and read-only surface assertions in `test_wallet_processor_secrets.py`.

### T8 — Public-ledger profiling and identity clustering

**Threat.** Cross-chain clustering of addresses with World ID nullifiers or free-form memo text enables profiling.

**Controls.**

- No identity-graph construction in processors.
- Nullifiers are commitment/HMAC-wrapped for public receipts; raw values are not retained in public projections.
- Free-form content default-redacted (T5).

**Tests.** Redaction and public-export cases; threat acceptance is documented here for operator review.

## Residual risks (accepted with monitoring)

| Risk | Residual | Owner |
| --- | --- | --- |
| Honest-but-curious export consumer correlates public addresses across chains | Accepted; out of processor scope | Data governance |
| Compromised secret manager yields live credentials | Accepted; processors never store materialised secrets | Platform secrets |
| Upstream provider maliciously shapes ledger history | Mitigated by finality/checkpoint rules; not eliminated | Chain risk |
| Operator enables raw/instruction retention with weak limits | Mitigated by hard caps; misconfiguration still possible | Operator runbooks |

## Release gate for WALPROC-G630

Release is blocked until:

1. This threat model is present and reviews the assets, threats, and controls above.
2. `python -m pytest -q ipfs_datasets_py/tests/security/test_wallet_processor_secrets.py ipfs_datasets_py/tests/security/test_wallet_processor_bounds.py` passes with **no failures and no expected xfails**.
3. Critical findings discovered by the review are closed via scoped repairs (WALPROC-049 / 060–063) rather than skipped assertions.

## Operator notes

- Prefer `vault://` or equivalent secret-manager references; never embed credentials in endpoints.
- Keep raw-payload and free-form retention policies at their fail-closed defaults unless a documented job requires opt-in custody.
- Treat public export artifacts as potentially personal even when secret-free.
- Any introduction of signing or broadcast requires a new threat-model revision and capability review.
