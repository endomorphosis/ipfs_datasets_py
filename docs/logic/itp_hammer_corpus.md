# ITP Hammer Content-Addressed Premise Corpus and Theorem Manifest

Status: Implemented (HAMMER-003)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.corpus`
Tests: `tests/unit_tests/logic/hammers/test_corpus.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract this module's `corpus_revision` values are threaded
through), `docs/logic/itp_hammer_capability_inventory.md` (HAMMER-002, the
environment/capability probe this module does not depend on).

## 1. Purpose

Premise selection (HAMMER-004/HAMMER-005) and every downstream hammer stage
need a single, auditable answer to "which theorems and premises were
available, and where did they come from?" This document specifies the
versioned corpus manifest that answers that question: a content-addressed
collection of theorem/premise identities, each tied to a *declared* upstream
source corpus, a source ITP, its imports, a normalized-statement digest, and
license metadata — with a deterministic `revision` digest over the whole
manifest that is exactly the `corpus_revision` value carried by every
`HammerRequest` and `HammerResult` defined in HAMMER-001.

Without this module, "the hammer used premise X" is an unverifiable claim.
With it, "the hammer used premise X from corpus revision R" can be checked
mechanically: R's content hashes to a specific, reproducible digest, X exists
in R with a specific normalized-statement digest, and X's license and
provenance are recorded alongside it.

## 2. Ingest only declared theorem corpora

A theorem or premise may only be ingested into a `CorpusManifest` against a
`corpus_id` that has first been registered as a `CorpusSource` via
`CorpusManifest.register_source`. Attempting to ingest against an
unregistered `corpus_id` raises `UndeclaredCorpusSourceError`. This is a
deliberate, load-bearing restriction — it rules out ad hoc, anonymous, or
untracked premises entering the pipeline through a side door. Every premise
the hammer pipeline ever cites must be traceable back to one specific,
versioned upstream snapshot.

A `CorpusSource` records:

| Field | Meaning |
| --- | --- |
| `corpus_id` | Stable identifier of the corpus within the manifest (e.g. `"mathlib4"`, `"rocq-stdlib"`, `"afp"`). |
| `name` | Human-readable name. |
| `source_itp` | The `ITPKind` (`lean` \| `coq` \| `isabelle`) this corpus's theorems are native to. |
| `version_ref` | The exact upstream snapshot ingested — a git commit, tag, or release version. Never a floating "latest" reference, so ingestion is always reproducible. |
| `license_id` | Default SPDX license identifier for theorems from this corpus (e.g. `"Apache-2.0"`). |
| `license_url` | Optional URL to the license text. |
| `homepage` | Optional URL to the corpus's homepage/repository. |
| `description` | Optional human-readable description. |
| `metadata` | Free-form, non-authoritative caller metadata. |

Re-registering an already-known `corpus_id` with byte-identical metadata is
an idempotent no-op (safe to call repeatedly, e.g. from an ingestion job that
reruns on every CI trigger). Re-registering it with *different* metadata — a
new `version_ref`, a changed `license_id`, a different `source_itp`, etc. —
raises `CorpusSourceConflictError`, because that would silently change the
provenance of every theorem already ingested under that corpus without any
explicit signal that provenance changed.

## 3. Theorem identity and content

Each ingested `TheoremEntry` records:

| Field | Meaning |
| --- | --- |
| `theorem_id` | Stable identity of the theorem within the manifest (e.g. `"Nat.add_comm"`). |
| `corpus_id` | The declared `CorpusSource` this entry was ingested from. |
| `source_itp` | ITP the statement is native to; must match the owning corpus's `source_itp`. |
| `imports` | Sorted, de-duplicated list of module/theory/file dependencies the statement requires. |
| `statement` | The raw statement text, as authored. |
| `normalized_statement` | The canonicalized form of `statement` (see §4) used to compute `statement_digest`. |
| `statement_digest` | The **normalized statement digest** — a deterministic `"sha256:<hex>"` digest of `normalized_statement`. This is the value theorem identity is checked against (see §5). |
| `license_id` | SPDX license identifier for this specific theorem (defaults to the owning corpus's `license_id`, overridable per theorem). |
| `license_url` | Optional URL to the license text (defaults to the owning corpus's `license_url`, overridable per theorem). |
| `content_digest` | A **CID or deterministic content digest** (see §6) of this entry's canonical, identity-defining fields. Always derived, never caller-supplied. |
| `metadata` | Free-form, non-authoritative caller metadata (e.g. source file path, line number). |
| `ingested_at` | When this entry was ingested (diagnostic only — deliberately excluded from every content digest, see §7). |

`TheoremEntry` instances are built exclusively through `TheoremEntry.create`
(used internally by `CorpusManifest.add_theorem`), which derives
`normalized_statement`, `statement_digest`, and `content_digest` from
`statement` — none of these can be supplied directly by a caller, so an
entry's digests can never drift from, or be spoofed independently of, its
actual statement text.

## 4. Statement normalization

`normalize_statement` is an intentionally simple, ITP-agnostic canonicalizer:
it applies Unicode NFC normalization, unifies line endings, strips
leading/trailing whitespace per line, drops blank lines, and collapses runs
of horizontal whitespace to a single space. It does **not** parse or
understand Lean/Coq/Isabelle syntax, and it does not attempt semantic
equivalence across syntactically different but logically identical
statements. Its only job is to make trivial formatting noise (CRLF vs LF,
trailing spaces, extra blank lines, decomposed vs precomposed Unicode) not
spuriously change a theorem's identity digest, while any genuine change to
the statement's content still changes `statement_digest`.

## 5. Rejecting duplicate identities with different statements

`CorpusManifest.add_theorem` enforces theorem identity as a promise about a
single, fixed statement:

- Ingesting a `theorem_id` that already exists in the manifest, with a
  statement whose `statement_digest` matches the existing entry's (and the
  same `corpus_id`/`source_itp`), is an **idempotent no-op** — the original
  entry (including its original `ingested_at`) is returned unchanged. This is
  what makes re-running an ingestion job against an unchanged upstream
  snapshot safe.
- Ingesting a `theorem_id` that already exists with a **different**
  `statement_digest`, or the same statement under a **different**
  `corpus_id` or `source_itp`, raises `DuplicateTheoremIdentityError`. This
  is the "reject duplicate identities with different statements"
  requirement: a theorem identity can never be silently repointed at a
  different statement, a different upstream corpus, or a different ITP.

```python
manifest.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4",
                      statement="forall a b : Nat, a + b = b + a")
# Re-ingesting the identical statement (even with different whitespace) is a no-op:
manifest.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4",
                      statement="forall a b : Nat,   a + b = b + a  ")
# Ingesting a different statement under the same identity raises:
manifest.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4",
                      statement="forall a b : Nat, a * b = b * a")
# -> DuplicateTheoremIdentityError
```

## 6. Content digests and CIDs

`compute_content_digest(payload)` serializes `payload` to canonical JSON
(sorted keys, `ensure_ascii=True`, no floating-point/locale ambiguity) and
hashes it with SHA-256. When the optional `multiformats` package is
importable, the digest is additionally wrapped as a real CIDv1 (`base32`
multibase, `raw` multicodec, `sha2-256` multihash) string such as
`"bafkrei..."`; when `multiformats` is unavailable for any reason, a plain
`"sha256:<hex>"` string is returned instead. Both forms satisfy the "CID or
deterministic content digest" requirement equally — callers must treat the
result as an opaque string to be compared for equality, never parsed.

`TheoremEntry.content_digest` is computed over the entry's
identity-defining fields only (`theorem_id`, `corpus_id`, `source_itp`,
`imports`, `statement_digest`, `license_id`, `license_url`) — deliberately
excluding `content_digest` itself (circular) and `ingested_at`
(non-deterministic wall-clock time; see §7).

## 7. The manifest revision

`CorpusManifest.revision` is a deterministic digest, computed with
`compute_content_digest`, over every registered `CorpusSource` and every
ingested `TheoremEntry` (each entry's revision-relevant fields, i.e. its
`to_dict()` output minus `ingested_at`), sorted by id for reproducible
ordering. Two independently constructed manifests with byte-identical
sources and theorems always produce the same `revision`, regardless of when
each was built or what `manifest_id` was assigned to it (`manifest_id` is a
caller-assigned label, not part of the content digest).

`revision` is exactly the `corpus_revision` value that must be carried on
every `HammerRequest` and `HammerResult` from HAMMER-001:

```python
manifest = CorpusManifest(manifest_id="itp-hammer-corpus")
manifest.register_source(CorpusSource(
    corpus_id="mathlib4", name="Mathlib4", source_itp=ITPKind.LEAN,
    version_ref="<pinned commit>", license_id="Apache-2.0",
))
manifest.add_theorem(theorem_id="Nat.add_comm", corpus_id="mathlib4",
                      statement="forall a b : Nat, a + b = b + a")

request = HammerRequest(..., corpus_revision=manifest.revision)
```

## 8. Retaining the corpus revision in every hammer result

`verify_hammer_result_corpus(result, manifest)` is the mechanical check that
a `HammerResult` (HAMMER-001) is genuinely bound to a specific corpus
manifest snapshot:

- `result.corpus_revision` and `result.request.corpus_revision` must both
  equal `manifest.revision`.
- Every `PremiseRecord` in `result.premises` must carry
  `corpus_revision == manifest.revision` and its `premise_id` must exist as
  a `theorem_id` in the manifest.

Any mismatch raises `CorpusRevisionMismatchError`. This closes the loop
between HAMMER-001's trust contract (which already requires every
`HammerRequest`/`HammerResult`/`PremiseRecord` to carry a `corpus_revision`
and enforces internal consistency between `HammerResult.corpus_revision` and
`HammerResult.request.corpus_revision`) and this module's corpus manifest:
`verify_hammer_result_corpus` additionally proves that revision actually
*resolves* to a real manifest whose entries genuinely contain every premise
cited.

## 9. Serialization and persistence

Every record (`CorpusSource`, `TheoremEntry`, `CorpusManifest`) exposes
`to_dict()`/`from_dict()` for JSON-compatible (de)serialization, following
the same conventions as the HAMMER-001 records. `CorpusManifest` additionally
exposes `to_json()`/`from_json()` and `save(path)`/`load(path)` for
persisting a versioned manifest as a JSON document on disk (or, via IPFS-aware
storage layered on top in a later taskboard item, content-addressed
storage). `CorpusManifest.to_dict()["revision"]` is always present for
inspection, but `from_dict` recomputes and never trusts a stored `revision`
value — it is dropped on load and recomputed from the deserialized sources
and entries, so a manifest's revision can never be corrupted or spoofed by
editing a persisted JSON file's `revision` key directly.

## 10. Non-goals of this module

This module defines corpus ingestion and identity only. It does not:

- Rank, select, or score premises for a given goal — that is HAMMER-004
  (deterministic baseline) and HAMMER-005 (optional learned selector).
- Translate premises to TPTP/SMT-LIB — that is HAMMER-007.
- Discover which ITPs/solvers are installed — that is HAMMER-002 (the
  capability inventory), which this module does not depend on.
- Provide IPFS pinning/retrieval of manifest content — `save`/`load` operate
  on the local filesystem only; wiring this manifest into IPFS-aware
  storage is in scope for HAMMER-012 (receipts).
