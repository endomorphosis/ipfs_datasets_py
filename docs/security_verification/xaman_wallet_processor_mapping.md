# Xaman Wallet Processor ↔ Formal Assurance Mapping

Goal: `WALPROC-G220`  
Task: `WALPROC-026`  
Track: `xaman-assurance`

This document maps **runtime** Xaman wallet-processor records to **formal**
assurance inputs without coupling the two layers. It is the human-readable
companion to:

| Artifact | Role |
| --- | --- |
| `ipfs_datasets_py/processors/wallets/xaman/assurance.py` | One-way projection adapter (runtime → assurance inputs) |
| `tests/contract/processors/wallets/test_xaman_assurance_bridge.py` | Contract tests for boundary + projection |
| `tests/fixtures/wallets/xaman/assurance_links.json` | Typed formal-asset inventory freeze (WALPROC-G020) |
| `tests/fixtures/wallets/xaman/runtime_projection_boundary.json` | Import / ownership boundary |

## Outcome

Preserve Xaman formal and security models under `logic/`. Do **not** move formal
reports into the runtime package. Add a narrow, offline projection from runtime
records to assurance inputs. Formal artifact relocation is a **separate** task
and only if inventory proves true runtime duplication.

## Layer Ownership

| Layer | Location | AST / entry symbols | Role |
| --- | --- | --- | --- |
| Runtime processor | `ipfs_datasets_py/processors/wallets/xaman/` | `XamanWalletProcessor`, `XamanPayload`, `PayloadStatus` | Payload lifecycle, network binding, redacted export, XRPL settlement composition |
| Runtime XRPL | `ipfs_datasets_py/processors/wallets/xrpl/` | `XRPLWalletProcessor` | Public-ledger facts used for settlement verification |
| Projection bridge | `…/xaman/assurance.py` | `project_payload_to_assurance`, `RuntimeAssuranceProjection` | One-way typed projections only |
| Formal IR adapter | `logic/security_ir/xaman/` | Xaman Security IR adapter / config | Immutable security IR boundary |
| Formal extractors | `logic/security_models/crypto_exchange/extractors/` | `xaman_source_extractor`, runtime-trace ingestor | Source / trace extraction for models |
| Formal reports | `logic/security_models/crypto_exchange/reports/` | assurance packet, protocol projection, verdicts | Offline analysis and release-decision envelopes |
| Security model IR | `logic/security_models/crypto_exchange/ir/schema.py` | `SecurityModelIR` | Shared IR schema for formal models |

Runtime paths and formal paths are intentionally disjoint. The bridge records
formal path **strings** for inventory; it never imports those modules.

## Coupling Rules (fail closed)

1. **Runtime → formal projection only.** Runtime may emit public, redacted,
   typed records and assurance projections. Formal tools may consume them offline.
2. **No formal into runtime.** Runtime modules must not import:
   - proof tools / solver portfolios;
   - report generators (assurance packets, disproof suites, release verdicts);
   - archive corpora loaders used only by formal analysis;
   - Firebase harnesses;
   - native vault assessment / preflight / fuzz modules;
   - device-trial or device harness modules.
3. **Assurance is not runtime correctness.** A formal pass does not prove the
   ingest path is correct; runtime settlement still requires XRPL evidence.
4. **Assurance status is not runtime authorization.** Projected
   `AssuranceStatus` values must not grant or deny wallet operations.
5. **Assurance status is not release proof.** Projections are not release-gate
   packets and must not be treated as production security sign-off.

These rules match fixture bridge IDs `BRIDGE-XAMAN-001` … `BRIDGE-XAMAN-003`
and the runtime boundary inventory under `tests/fixtures/wallets/xaman/`.

## Projection Domains

Every runtime projection covers the five acceptance domains:

| Domain | Runtime source | Projected facts (examples) | Status meaning |
| --- | --- | --- | --- |
| **network binding** | `XamanPayload.network`, `account`, `payload_uuid`, destination fields | Network id, account, payload UUID, destination tag | Observed when identity is bound at normalize time |
| **payload lifecycle** | `PayloadStatus`, API flags (`api_signed`, `api_resolved`, …) | Distinct lifecycle state; digests; API success flag | Observed for every normalized payload; states remain distinct |
| **signing decision** | API lifecycle (`signed` / `rejected`) | `api_signed`, explicit `runtime_can_sign=false` | Observed API decision only — **not** vault crypto proof and **not** authorization to sign |
| **submission** | `submitted` status and/or `transaction_hash` | Txid presence; `runtime_can_submit=false` | Observed remote submit fact — processor never submits |
| **finality assumptions** | `SettlementVerdict` from XRPL composition | `settlement`, `is_ledger_settled`, A6/A9 assumptions | XRPL-validated → observed finality fact; API success alone → assumed / non-settled |

### Finality assumptions (explicit)

- API success is **never** settlement (`api_success_is_settlement: false`).
- Ledger settlement is verified only through the composed XRPL processor.
- Assumptions carried on the projection (declarative, not proved here):
  - **A6** — the declared XRPL finality threshold is sufficient;
  - **A9** — external XRPL providers may lie, delay, or censor only within modeled bounds.

## One-way Data Flow

```text
Xaman API / fixtures          XRPL ledger evidence
        │                              │
        ▼                              ▼
 XamanWalletProcessor ──────compose──► settlement.verify_settlement_against_xrpl
        │
        │  XamanPayload / public ledger records
        ▼
 assurance.project_payload_to_assurance
 assurance.project_ledger_record_to_assurance
        │
        │  RuntimeAssuranceProjection (offline, non-authoritative)
        ▼
 formal consumers under logic/  (SecurityModelIR, reports, extractors)
        │
        ✗  never imported by runtime processors
```

Direction constant: `runtime_to_formal_projection`.

## Runtime Record → Projection Field Map

| Runtime field | Domain | Assurance input field |
| --- | --- | --- |
| `payload_uuid` | network binding, identity | `payload_uuid` |
| `network` | network binding | `network` |
| `account` / `destination` / `destination_tag` | network binding | same |
| `status` (`PayloadStatus`) | payload lifecycle | `domains.payload_lifecycle.facts.status` |
| `api_signed` / `api_resolved` / … | payload lifecycle, signing | lifecycle flags; signing decision |
| `transaction_type` | payload lifecycle | `transaction_type` |
| `transaction_hash` | submission, finality | submission txid; finality anchor |
| `content_digest` / `raw_meta_digest` | payload lifecycle | digests only (no secret material) |
| `settlement` / `settlement_detail` | finality assumptions | settlement verdict + detail |
| `is_ledger_settled` | finality assumptions | boolean from XRPL-validated only |
| public ledger sample fields | network / submission / finality | `project_ledger_record_to_assurance` |

Private keys, seed phrases, vault secrets, Firebase attributes, device traces,
and raw signed blobs are **out of scope** for this projection.

## Formal Assets (remain in place)

The projection adapter inventories formal assets as path strings. Existing
locations (do not relocate under WALPROC-G220):

- `logic/security_ir/xaman/adapter.py`
- `logic/security_ir/xaman/config.py`
- `logic/security_models/crypto_exchange/extractors/xaman_source_extractor.py`
- `logic/security_models/crypto_exchange/extractors/xaman_runtime_trace_ingestor.py`
- `logic/security_models/crypto_exchange/reports/xaman_assurance_packet.py`
- `logic/security_models/crypto_exchange/reports/xaman_protocol_projection.py`
- `logic/security_models/crypto_exchange/ir/schema.py` (`SecurityModelIR`)

Related offline documentation already under `docs/security_verification/`
(payload lifecycle model, security model IR, testnet runtime mapping, etc.)
continues to describe formal analysis. This mapping does not supersede those
artifacts; it links the **wallet processor runtime** to them.

## Non-goals

- Approving, signing, or submitting Xaman payloads at runtime.
- Importing or executing proof tools, Apalache/Tamarin solvers, or disproof suites from the processor package.
- Treating assurance projections as UCAN/capability grants or release certificates.
- Relocating formal modules into `processors/wallets/xaman/`.
- Claiming production Xaman client equivalence from public-ledger observations.

## Validation

```bash
python -m pytest -q ipfs_datasets_py/tests/contract/processors/wallets/test_xaman_assurance_bridge.py
```

The contract suite asserts:

1. runtime import boundary (no formal/harness coupling);
2. formal modules remain at existing paths;
3. all five projection domains are populated;
4. assurance status is not runtime authorization and not release proof;
5. this mapping document covers the acceptance terms above.

## Acceptance Checklist (WALPROC-G220)

- [x] Runtime imports no proof tool, report generator, archive corpus, Firebase, native vault, or device harness.
- [x] Formal modules stay at existing paths unless separately mapped.
- [x] Projection covers network binding, payload lifecycle, signing decision, submission, and finality assumptions.
- [x] Assurance status is not runtime authorization or release proof.
- [x] Mapping documented; one-way projection tests land without moving formal reports.
