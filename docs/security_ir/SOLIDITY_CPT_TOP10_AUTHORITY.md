# Solidity CPT Top-10 source, license, and release authority

Status: normative for CRYPTOIR-G710 / CRYPTOIR-037
Machine policy: `ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.release_policy`

This document freezes the corpus source and the authority boundary that applies
before ingestion, graph construction, retrieval, formalization, training, or
release. It is an engineering policy, not a legal opinion. Publication of raw
source or learned weights requires **separate license review and operator authority**.

The contracts deliberately follow the reviewed CVEfixes Security IR governance
pattern at `origin/integration/cvesir-ipfs-accelerate`, commit
`3952dae8925e9f469632ed53eccf1678a924fd4e`. They use one source profile, one
license-provenance vocabulary, and one release policy rather than introducing a
parallel identity or authority framework.

## 1. Immutable source profile

The only admitted upstream profile is:

| Fact | Pinned value |
| --- | --- |
| Dataset | `samscrack/solidity-cpt-top10-quality` |
| Immutable revision | `23c0b2f279fa29c6b425543fe9c8bf41d574d028` |
| Config / split | `default` / `train` |
| LFS object | `top10.parquet` |
| Object SHA-256 | `185f1ac548f0df10a8166c8a2a10610bcc3422ce77f51567c3de86ddc8f5e455` |
| Object size | `109124886` bytes |
| Rows | `23471` |
| Ordered schema | `text`, `source`, `address`, `name`, `compiler`, `license`, `path`, `n_chars` |
| Dataset-level declaration | CC BY 4.0 (`CC-BY-4.0`) |

`SourceProfile.verify_observation()` compares observed metadata to all required
facts. A moving branch, missing field, different shard, digest mismatch,
truncation, row-count drift, or reordered/changed schema fails closed before a
row is admitted.

The word `top10` means the dataset author's **top-decile quality** selection. It
is not an OWASP Top 10 label, vulnerability truth, audit result, or evidence
that any contract is secure. It cannot be converted into a safety label.

## 2. Non-interchangeable license evidence

Dataset-level and per-row license evidence are separate records:

- The dataset-level record preserves the Hub declaration for the exact pinned
  revision.
- Each per-row record preserves the row index and original `license` metadata.
  It does not inherit raw-source redistribution rights merely because the
  dataset has a CC BY 4.0 declaration.

An absent, malformed, or ambiguous per-row value such as `unknown`, `other`,
`custom`, or `proprietary` defaults to **internal/source-free** use. A
recognizable SPDX-like value is still unreviewed evidence until a reviewer
records a narrower determination. Source-free derivatives may contain
content digests, typed structure, provenance, and bounded metadata, but no raw
`text` body from the row.

The machine policy treats these permissions independently:

1. Internal research and source-free derived use.
2. Raw-source redistribution.
3. Model/checkpoint or learned-weights publication.

Raw-source redistribution and learned-weights publication each require:

- reviewed license evidence bound to the exact source revision and artifact
  kind; and
- a separate operator-authority record.

Neither an objective, a test result, a dataset declaration, nor possession of
credentials supplies those approvals. The default workflow performs no
publication.

## 3. Untrusted-input threat model

Every field in `top10.parquet`, especially Solidity `text`, comments, string
literals, paths, source names, compiler declarations, addresses, and license
tokens, is **inert untrusted data**.

Controls and required downstream behavior:

| Threat | Required behavior |
| --- | --- |
| Prompt-like instructions in source/comments | Preserve as data only; never interpret as instructions or authority |
| Malicious Solidity, imports, assembly, or build directives | Never compile or execute as part of source admission |
| Path traversal or unusual repository paths | Validate and quarantine; never use an untrusted path as a write target |
| Embedded secrets or personal data | Quarantine/redact under a reviewed policy; never place raw bodies in source-free output |
| False compiler/address/verified-source claims | Preserve as unverified metadata; never assert deployed-bytecode equality |
| Schema, shard, revision, or count drift | Fail closed before row admission |
| License ambiguity | Restrict to internal/source-free use |
| Quality, retrieval, or model score inflation | Keep as candidate evidence; never convert to vulnerability, proof, safety, or enforcement authority |

Imports of the governance package perform no I/O. Network clients, credentials,
dependency installation, compiler invocation, source execution, model loading,
training, and upload belong to later explicit components and authority gates.

## 4. Default-denied authority

The source profile and release policy forbid every ambient capability. The
following names are recorded explicitly because they are acceptance-critical:

| Capability | Default boundary |
| --- | --- |
| `network` | No download, RPC, Hub lookup, credential discovery, or import resolution |
| `execution` | No source evaluation, Solidity compilation, EVM execution, or prompt interpretation |
| `training` | No optimizer/model run or checkpoint materialization |
| `upload` | No raw source, derivative, checkpoint, or learned-weights publication |
| `proof` | No theorem authority from quality, retrieval, model, SAT, simulation, or an unexecuted candidate |
| `enforcement` | No contract-safety `ALLOW`, wallet authorization, signing, broadcast, or transaction decision |

Unknown authority names also fail closed. A later component may act only under
its own reviewed policy and explicit operator grant; it cannot mutate this
corpus policy or reinterpret a corpus record as permission.

## 5. Publication decisions

`SolidityCPTReleasePolicy.evaluate_publication()` is a pure, deterministic
decision function. It does not copy, upload, or expose source. Its decision
binds:

- the exact source-profile digest;
- the release-policy digest;
- separate dataset-level and per-row license evidence;
- the requested artifact kind; and
- for raw source or learned weights, separate license-review and
  operator-authority identifiers.

Metadata and source-free derivatives can be admitted under the reviewed
dataset evidence even when a row is ambiguous, because the source body remains
excluded. Rejected row evidence fails closed. Raw source and learned weights
are denied unless both independent approvals and the corresponding reviewed
row permission are present.

The decision is evidence only. It does not perform upload, prove a property,
declare a contract safe, or authorize a transaction.

## 6. Acceptance evidence

`tests/unit/logic/security_ir/solidity_cpt_top10/test_release_policy.py`
machine-checks:

1. The exact revision, LFS digest, size, row count, and ordered schema.
2. Immutable source-profile drift rejection.
3. Separation of dataset-level and per-row license provenance.
4. The internal/source-free default for ambiguous and unreviewed rows.
5. Inert untrusted data and the top-decile-not-OWASP/safety boundary.
6. Default denial of network, execution, training, upload, proof, and
   enforcement authority.
7. Separate license review and operator authority for raw source and learned
   weights.
8. Deterministic, source-free policy and publication-decision serialization.

## 7. Related authority

- `docs/crypto_ir/AUTHORITY_AND_POLICY.md` defines the shared Crypto IR
  non-interchangeable authority lattice.
- `docs/planning/CRYPTO_IR_COMPLIANCE_PLAN.md` section 14 defines the larger
  Solidity CPT program and source-threat boundary.
- A later `SOLIDITY_CPT_TOP10_RELEASE_AND_ROLLBACK.md` will govern actual
  staging, promotion, and rollback; this policy does not grant those actions.
