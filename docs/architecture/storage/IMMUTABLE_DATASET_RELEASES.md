# Immutable dataset build, publish, and load lifecycles

| Field | Value |
| --- | --- |
| Interface | `ImmutableDatasetReleaseLifecycle@1` |
| Task | `IPFSDOC-025` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/voice/` (schema, normalize, graphrag, materialize, audio_quality, hf_release, release_loader); `ipfs_datasets_py/huggingface/` (release, publisher, repository, snapshot, bucket); [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after voice schema, HF release/publisher, or quality-gate policy changes |

> **Companion guides:** Content identity (CID/IPLD/CAR) lives in
> [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md). Backend
> routers, pins, and caches live in
> [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md). Peer
> distribution and the thin publication surface overview live in
> [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md). **This guide owns the
> bespoke immutable release plane:** schema → normalize/quarantine → quality
> gates → offline materialization → byte-identical Parquet shards →
> approval-gated append-only publish → pinned load → pointer canary/rollback.

## 1. Purpose

This guide answers: **how an immutable dataset release is built, verified,
published, loaded, canaried, and rolled back**—using the Abby **voice**
package and the generic **Hugging Face** release/publication packages as the
reference implementation. It defines the dry-run boundary that autonomous
workers must not cross, the integer quality gates that keep receipts
canonical, and the identity rules that keep shards byte-identical across
rebuilds.

## 2. Audience

- **Primary:** developers and operators building or promoting voice (and
  sibling) dataset releases; agents interpreting dry-run receipts without
  inventing publication success.
- **Secondary:** architects placing release planes relative to content
  addressing and P2P distribution; GraphRAG runtime owners restoring pinned
  indexes.

## 3. Scope and non-goals

### In scope

- Canonical flat schema for voice rows (response, template, audio, provenance,
  evaluation) and Arrow/Parquet/Hugging Face Feature adapters.
- Deterministic normalization, quarantine records, and quality reports.
- Safe GraphRAG ingestion: slotted templates as plans, not live facts;
  CID-bearing evidence binding.
- Offline materialization: pinned sources, worksets, TTS/ASR job specs, local
  release receipts (no remote write).
- Integer (basis-point) audio quality gates and publishable consent.
- Deterministic sharded ZSTD Parquet construction and file descriptors
  (`sha256`, size, content **CID**).
- Approval-gated **append-only** publishing: **dry-run** plan/cost receipt,
  human **approval**, commit SHA + digest verification, pinned redownload.
- Runtime release pointer: canary promotion and **rollback** without delete.
- Revision-pinned loaders that reject mutable refs (`main` / `latest`).
- Compatibility identity aliases for snapshot/cache types (SkillCenter wire
  schema retained under Hugging Face names).

### Non-goals

- Peer discovery, task queues, and IPFS cluster operator product (P2P guide).
- CID codec math and IPLD block storage internals (content-addressing guide).
- Hosting Hugging Face Hub or IPFS infrastructure.
- Implementing production code changes in this documentation task.
- Treating a dry-run receipt, mock pin, or branch name as an immutable release.

## 4. Context

Dataset releases must be **immutable, rebuildable, and fail-closed**:

1. **Identity** is content-addressed (full SHA-256 and derived content CID),
   not a branch tip, basename, or local path ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).
2. **Build** is offline and deterministic: same pinned rows + policy →
   **byte-identical** Parquet shards and manifests.
3. **Publish** is a separate, human-approved remote-write boundary. Default
   entrypoints are dry-run only.
4. **Load** pins an immutable Hub **revision** (commit SHA). Mutable refs are
   rejected so runtime GraphRAG cannot silently drift.
5. **Promotion** moves only a runtime pointer (canary percent). Failed releases
   are retained; rollback never deletes.

The voice package is the full domain lifecycle. The Hugging Face package owns
generic Parquet release helpers, repository revision contracts, content-
verified snapshot cache, and the append-only publisher. Domain builders wrap
the helpers; they must not invent parallel identity fields or skip the dry-run
gate.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Voice schema v2 contracts and stable IDs | Hub hosting or IPFS Cluster consensus |
| Normalization / quarantine / quality reports | Live speech-model training stacks |
| Safe GraphRAG slotted index offline core | Full enterprise GraphRAG product ops |
| Offline materialization and workset planning | Autonomous remote TTS fleets as authority |
| Integer audio quality policy and gates | Fuzzy “good enough” acceptance |
| Deterministic HF release construction (local) | Approval authority for production write |
| Append-only publication plan/commit/verify | Deleting or rewriting legacy Hub objects |
| Runtime pointer canary and rollback semantics | Mutable branch-based deployment |
| Pinned release loaders and streaming revision pins | Treating `main` as production identity |
| Compatibility aliases for snapshot types | Changing SkillCenter wire schema equality |

**Inbound callers:** release builders, operator scripts, MCP/CLI publication
wrappers, GraphRAG runtime restore, offline validation harnesses, autonomous
agents (through dry-run only).

**Outbound dependencies:** optional `pyarrow` for Parquet; optional
`huggingface_hub` / injected `HfApi` for commit; optional
`datasets.load_dataset` for revision-pinned streaming; CID helpers from
`logic.ir_core.identity`; optional TTS/ASR executors via injected providers.

**Authority notes:** A dry-run plan digest, publication approval id, Hub commit
SHA, content CID, pin status, and GraphRAG `index_cid` answer different
questions. Do not collapse them in logs or agent prompts.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Voice package entry | `voice/__init__.py` | Canonical contracts; lazy data-manager / materialize exports |
| Flat schema v2 | `voice/schema.py` | Response / template / audio / provenance rows; Arrow/HF features; `validate_publishable` |
| Evaluation schema | `voice/evaluation_schema.py` | Fifth flat config for evaluation rows |
| Normalizer | `voice/normalize.py` | Deterministic normalize + quarantine + quality report |
| Audio quality | `voice/audio_quality.py` | Integer basis-point gates (WER/CER/silence/clipping/slots) |
| Reconcile | `voice/reconcile.py` | Receipt-to-row promotion under quality policy |
| GraphRAG | `voice/graphrag.py` | `SlottedResponseIndex`, evidence binding, graph/index CIDs |
| Materialize | `voice/materialize.py` | Offline worksets, job specs, local release receipt |
| Dataset manager | `voice/dataset_manager.py` | Pinned sources and disposition |
| Workset | `voice/workset.py` | Deterministic audio work items/manifests |
| Legacy sources | `voice/legacy_sources.py` | Discovery hints only; never identity |
| HF release builder | `voice/hf_release.py` | Five flat configs → sharded ZSTD Parquet + manifest |
| Release loader | `voice/release_loader.py` | Revision-pinned load / streaming restore |
| HF release helpers | `huggingface/release.py` | `FileDescriptor`, `write_zstd_parquet`, contamination checks |
| HF publisher | `huggingface/publisher.py` | Dry-run, approval, append-only commit, verify, canary/rollback |
| Repository revision | `huggingface/repository.py` | Immutable repository revision contracts |
| Snapshot cache | `huggingface/snapshot.py` | Content-verified cache; compatibility aliases |
| Bucket inventory | `huggingface/bucket.py` | Pinned bucket object inventory (read path) |

```text
Pinned sources / legacy inventory
        |
        v
  normalize + quarantine  -----> quality report (integer gates)
        |
        v
  offline materialize (workset, TTS/ASR receipts, local artifacts)
        |
        v
  AbbyVoiceHFReleaseBuilder  -->  ZSTD Parquet shards + descriptors + release_cid
        |                         (byte-identical rebuild; local only)
        v
  HuggingFaceReleasePublisher.plan_dry_run
        |   *** AUTONOMOUS WORKER HARD STOP ***
        |   (receipt status: dry_run_only / awaiting_human_approval)
        v
  PublicationApproval (human) --> publish_append_only (create_commit)
        |
        v
  post-publication verification + pinned redownload validation
        |
        v
  canary_promote_pointer  /  rollback_pointer  (never delete release)
        |
        v
  AbbyVoiceReleaseLoader (commit SHA pin) --> SlottedResponseIndex
```

## 7. End-to-end lifecycle

### 7.1 Schema (flat, immutable rows)

Voice data is four (plus evaluation) **separate** flat schemas so Arrow,
Parquet, and Hugging Face Dataset Viewer never mix heterogeneous JSON shapes:

| Schema constant | Row type | ID field |
| --- | --- | --- |
| `abby_voice_response_v2` | `AbbyVoiceResponse` | `response_id` |
| `abby_voice_template_v2` | `AbbyVoiceTemplate` | `template_id` |
| `abby_voice_audio_v2` | `AbbyVoiceAudio` | `audio_id` |
| `abby_voice_provenance_v2` | `AbbyVoiceProvenance` | `provenance_id` |
| `abby_voice_evaluation_v2` | `AbbyVoiceEvaluation` | `evaluation_id` |

Rules:

- Only scalars, nullable scalars, and consistently typed `list[str]` columns.
- Rows are frozen dataclasses; `to_dict()` emits JSON-safe lists in column
  order (`schema_columns`).
- Stable IDs are content-derived (`stable_response_id`, `stable_template_id`,
  `stable_audio_id` from `content_sha256`, `stable_provenance_id`) without
  wall-clock or mutable storage paths.
- Publishable consent is restricted (`granted`, `not_required`);
  `validate_publishable` fails closed otherwise.
- Optional adapters: `get_pyarrow_schema` / `get_huggingface_features` for
  Parquet and Hub configs.

### 7.2 Deterministic normalization and quarantine

`AbbyVoiceDatasetNormalizer` (`voice/normalize.py`) converts legacy IndexTTS-
style manifests into canonical v2 rows **without mutating inputs**.

Invariants:

- No wall-clock time, input array position, `random`, or Python `hash()`
  affects output identity.
- Rejected rows become `QuarantineRecord`s with stable source reference,
  source digest, and machine-readable `QuarantineReason` codes (for example
  `invalid_record`, `duplicate_text`, `duplicate_audio`, `missing_audio`,
  `audio_hash_mismatch`, `ungrounded_claim`, `inconsistent_slots`).
- Spoken text normalization (`normalize_spoken_text` /
  `normalize_indextts_spoken_text`) is deterministic; duplicates use
  normalized text identity, not basename.
- Quality report schema version: `abby_voice_quality_v2`.
- Deterministic train/validation/test split uses salt-bound hashing
  (`deterministic_split`), not random sampling.

Normalization is non-destructive discovery of publishable rows; it is not
publication.

### 7.3 Integer quality gates

Audio admission uses **integer basis points** (0..10_000) so receipts stay
JSON-safe and identity-stable (`voice/audio_quality.py`):

| Gate | Purpose | Example thresholds (policy v1) |
| --- | --- | --- |
| `integrity` | size / sha256 / media type | exact match |
| `decode` | decode success, sample rate, channels | 24 kHz mono default |
| `acoustic` | silence / clipping ratios | max silence 6000 bp; clipping 200 bp |
| `round_trip` | TTS→ASR WER/CER | max WER 1500 bp; CER 1000 bp |
| `slot_fidelity` | critical slots survive ASR | address, phone, hours, amount, … |
| `consent` | publishable consent only | granted / not_required |
| `policy` | versioned `AudioQualityPolicy` binding | stale policy fails closed |

Rates are **never** accepted as floating fuzzy scores in identity-bearing
receipts. `rate_to_basis_points`, `word_error_rate_bp`, and
`character_error_rate_bp` keep comparisons integer-canonical. Offline unit
paths may use deterministic synthetic WAV builders; live ASR providers are
injected and optional.

### 7.4 Safe GraphRAG

`SlottedResponseIndex` (`voice/graphrag.py`) turns validated rows into a
content-addressed template graph plus hybrid retrieval:

- Templates are **plans**, not current answers. Example slot values from
  training rows are never treated as live facts.
- Runtime resolution binds every placeholder from caller-supplied
  **CID-bearing** `EvidenceRecord`s for the current turn
  (`UnsafeSlotBindingError` on malformed evidence).
- Offline core is dependency-light: sparse vectors + graph snapshot with
  `graph_cid` and `index_cid`. Optional `IPLDKnowledgeGraph`,
  `IPLDVectorStore`, and `GraphRAGLLMProcessor` collaborators inject without
  changing offline identity when unused.
- Ingestion fails closed on conflicting IDs and referential breaks
  (`GraphRAGIngestionError`).
- Support indexes sit **beside** Parquet config directories, never inside
  Dataset Viewer row configs.

### 7.5 Offline materialization

`AbbyVoiceMaterializer` and related types (`voice/materialize.py`,
`dataset_manager.py`, `workset.py`) implement the reuse-first offline path:

1. Pin sources (`PinnedVoiceSource`) and bucket inventories as immutable.
2. Plan deterministic `VoiceAudioWorkset` / `VoiceAudioJobSpec` rows (task
   identity without audio bytes or credentials).
3. Execute TTS/ASR only through injected providers; capture
   `TTSASRExecutionReceipt`s.
4. Write local normalized artifacts and a **local** release receipt
   (`abby_voice_local_release_manifest_v1`).

Conflict policy: every transformation is deterministic and offline. Raw audio,
credentials, private transcripts, and mutable refs never enter identity-
bearing files. Materialization does **not** call Hub write endpoints.

### 7.6 Deterministic release construction (byte-identical shards)

`AbbyVoiceHFReleaseBuilder` (`voice/hf_release.py`) plus
`huggingface/release.py` perform **local** deterministic construction:

- Five flat configs: response, template, audio, provenance, evaluation.
- Sharded ZSTD Parquet with pinned writer settings
  (`compression=zstd`, level `6`, fixed row-group size, dictionary on,
  page index off) so two builds from the same ordered table produce
  **byte-identical** shards.
- Default shard size: 4096 rows (`DEFAULT_SHARD_ROWS`).
- Each file is described by a `FileDescriptor`: relative path, `size_bytes`,
  full lower-case SHA-256, content **CID** (`cid_v1_from_digest` of the raw
  digest), optional row_count/shard_id/split/config_name.
- Release manifest schema: `abby-voice-huggingface-release/v1` with
  `release_cid`, `graph_cid`, `index_cid`, policy digest, artifact manifest.
- `reject_identity_contamination` forbids timestamps, hostnames, local path
  markers (`/home/`, `file://`, …), and mutable Hub refs (`/resolve/main/`,
  `refs/heads/`, …) in identity-bearing manifests.
- `validate_abby_voice_hf_release` exhaustively rehashes and re-validates a
  local tree offline.

Publication and pointer promotion remain separate responsibilities.

### 7.7 Approval-gated append-only publishing

`HuggingFaceReleasePublisher` (`huggingface/publisher.py`) owns the remote-
write boundary:

| Step | Type | Network write? | Autonomous OK? |
| --- | --- | --- | --- |
| `plan_dry_run` | Diff ops + cost receipt + plan digest | **No** | **Yes** (hard stop here) |
| `PublicationApproval` | Human approver, plan_digest, cost/byte bounds | No | **No** (requires human) |
| `publish_append_only` | `HfApi.create_commit` under new release prefix | Yes | Only with approval + `dry_run=False` |
| `verify_post_publication` | Match remote digests to plan under commit SHA | Read | After approved commit |
| `redownload_and_validate_pinned` | Empty cache, rehash by commit SHA | Read | After approved commit |
| `canary_promote_pointer` | Runtime pointer + canary percent | Separate reviewed | Human reviewed |
| `rollback_pointer` | Restore previous pointer; retain failed release | Separate reviewed | Human reviewed |

**Append-only rules:**

- New objects land under an immutable prefix
  (default `data/abby_voice_v2/{release_id}`).
- Operations are **add only**. Prohibited: delete, move, force_push,
  overwrite_legacy, rewrite_main, basename-only skip.
- Exact path **and** digest match may skip re-upload; basename alone never
  skips.
- Mismatched existing remote object under the same path fails closed.
- Tokens/credentials never appear in plans, receipts, logs, or source control
  (`_reject_secrets`).

**Dry-run cost receipt** estimates transfer + monthly storage from byte totals
(`estimate_publication_cost`). The plan’s `plan_digest` binds operations and
cost; approval must match that digest and bounds.

**Default entrypoint** `publish_abby_voice_release(..., dry_run=True)` returns
`status: dry_run_only`. Setting `dry_run=False` without
`PublicationApproval` raises:
`human PublicationApproval is required when dry_run is false; autonomous work stops after a dry run`.

### 7.8 Commit and digest verification

After an approved commit:

1. **Commit receipt** records Hub `commit_sha` (40–64 hex), release_id,
   release_prefix, plan_digest, uploaded paths, approval_id.
2. **Post-publication verification** requires every planned remote path under
   that commit with matching full SHA-256 and byte length—never via `main`.
3. **Pinned redownload validation** requires an empty verified cache, fetches
   by commit SHA, rehashes, and fails closed on any mismatch.

Only after both residual gates pass is status
`published_pending_promotion`. Promotion is still a separate step.

### 7.9 Pinned loaders

`AbbyVoiceReleaseLoader` (`voice/release_loader.py`) is the revision-pinned
streaming/release loader:

- Requires a sealed release manifest and an **immutable commit SHA**.
- Rejects mutable revision markers: `main`, `master`, `head`, `latest`,
  `current`, and `/resolve/main/` paths.
- Validates `FileDescriptor`s with `verify_file_descriptor` before use.
- Downloads only the manifest, support indexes, and selected Parquet shards.
- Restores a content-addressed `SlottedResponseIndex` for runtime resolution.
- Hub streaming path: `datasets.load_dataset(..., revision=<commit_sha>,
  streaming=True)` wrapped so mutable defaults cannot sneak in.
- Offline fixtures may use `commit:<label>` only with the explicit prefix so
  branch names cannot pass as pins.

### 7.10 Pointer canary and rollback

Runtime consumers follow `RuntimeReleasePointer` (default path
`runtime/abby_voice_release_pointer.json`), not the latest Hub branch tip:

- `canary_promote_pointer`: sets `canary_percent` in 1..100, records
  previous commit/release, never deletes the prior release.
- `rollback_pointer`: restores previous_commit_sha / previous_release_id;
  requires `failed_release_retained=True` (no delete).
- Receipt statuses include `dry_run_only`, `awaiting_human_approval`,
  `published_pending_promotion`, `canary_active`, `promoted`, `rolled_back`,
  `blocked_remote_write_gate`.

A failed canary is operationally “point elsewhere,” not “erase history.”

### 7.11 Compatibility identity aliases

`huggingface/snapshot.py` re-exports SkillCenter snapshot types under Hugging
Face names **as intentional aliases** (not subclasses or copies):

- Class equality, snapshot identifiers, alias paths, and the
  `skillcenter-snapshot/v1` wire schema remain interchangeable for old and new
  callers.
- `HuggingFaceStaleCacheAliasError` preserves stale-alias fail-closed behavior
  when a cache pointer would claim a different content identity.
- Downloaded bytes promote only through the content-verified snapshot cache;
  no network access at package import time.

Domain packages must not fork parallel snapshot identity formats.

## 8. Kinds of truth (do not collapse)

| Kind | Example | Is not |
| --- | --- | --- |
| Content digest / CID | shard `sha256`, `content_cid`, `release_cid` | Hub path or pin status |
| Hub revision | 40+ hex `commit_sha` | Branch name `main` |
| Dry-run plan | `plan_digest`, cost receipt | Published release |
| Human approval | `approval_id` + matching plan_digest | Agent self-approval |
| Publication receipt | `append_only_commit_receipt` | GraphRAG answer quality |
| Runtime pointer | `RuntimeReleasePointer` + canary % | Existence of all historical prefixes |
| GraphRAG index | `index_cid` / `graph_cid` | Live factual authority of slot examples |
| Quarantine record | reason code + source digest | Deleted source |

## 9. Autonomous worker dry-run boundary

**Hard rule:** autonomous workers **must stop after documented dry-run**.

Allowed without human approval:

- Normalize, quarantine, quality gates, offline materialize.
- Local HF release build and offline validation.
- `plan_dry_run` / `publish_abby_voice_release(dry_run=True)`.
- Emit receipt with `status: dry_run_only` or `awaiting_human_approval`.
- Offline load from local trees pinned with explicit commit labels.

Forbidden without explicit human `PublicationApproval` and operator-injected
credentials/API:

- `dry_run=False` remote write.
- `publish_append_only` / `create_commit`.
- Pointer canary promotion or rollback in production.
- Persisting tokens into task rows, manifests, logs, or source control.
- Claiming “published”, “promoted”, or “production load pin advanced” from a
  dry-run receipt alone.

Agents that need to continue past the boundary must surface a clear handoff:
plan digest, cost bounds, and the exact approval fields required—not invent
approval.

## 10. Failure modes

| Failure | Behavior |
| --- | --- |
| Schema violation | `AbbyVoiceSchemaError` / fail closed |
| Quality gate fail | quarantine / non-publishable disposition; integer reason codes |
| Identity contamination in manifest | `reject_identity_contamination` raises |
| Local file ≠ descriptor digest | build/validate fail closed |
| Dry-run plan vs existing remote mismatch | refuse overwrite |
| Missing approval when not dry-run | raise; autonomous stop message |
| Approval digest/cost mismatch | refuse commit |
| Post-publication digest mismatch | verification fails; do not promote |
| Mutable revision on load | `AbbyVoiceReleaseLoaderError` |
| Rollback without previous pointer | fail closed; no delete of current |
| Stale snapshot cache alias | `HuggingFaceStaleCacheAliasError` |
| Optional pyarrow/hf_hub missing | import/build errors; offline identity rules unchanged |

## 11. Invariants

1. **Offline build identity is independent of Hub branch tips.**
2. **Same pinned rows + policy → byte-identical shards** (fixed Parquet writer).
3. **Descriptors bind path + size + sha256 + content CID** consistently.
4. **Normalization never mutates source mappings;** quarantine retains rejects.
5. **Quality metrics in receipts are integers (basis points), not floats.**
6. **GraphRAG templates are plans; evidence binds current facts with CIDs.**
7. **Publication is append-only under a new release_id prefix.**
8. **Autonomous workers stop at dry-run;** human approval gates remote write.
9. **Verification uses commit SHA + digests, never `main`/`latest`.**
10. **Canary/rollback move pointers only; releases are retained.**
11. **Secrets never enter identity-bearing artifacts or receipts.**
12. **Compatibility aliases preserve class equality and wire schema identity.**
13. **Fail closed on trust; degrade only optional execution features** (ADR-004).

## 12. Rationale and decisions

| Topic | Summary | Source |
| --- | --- | --- |
| Separate flat configs | Dataset Viewer/Arrow cannot safely mix heterogeneous JSON | `voice/schema.py` module doc |
| Quarantine over drop | Non-destructive; auditable reason codes | `voice/normalize.py` |
| Integer basis points | Stable, JSON-safe quality identity | `voice/audio_quality.py` |
| Templates as plans | Prevents training examples becoming live facts | `voice/graphrag.py` |
| Local build vs publish | Determinism offline; remote write is human-gated | `hf_release.py` + `publisher.py` |
| Append-only prefix | Never delete/rewrite legacy objects | `publisher.py` |
| Dry-run default | Autonomous safety boundary | `publish_abby_voice_release` |
| Pointer canary | Decouple publish from traffic cutover | `canary_promote_pointer` |
| Snapshot aliases | Interchange without identity fork | `huggingface/snapshot.py` |
| Kinds of truth | CID ≠ commit ≠ receipt ≠ pointer | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) |

## 13. Security, privacy, and trust boundaries

- Hub tokens and API credentials: inject at commit time only; never serialize
  into plans, approvals notes (credential-like patterns rejected), or receipts.
- Consent and license fields on descriptors gate publishability; denied or
  withdrawn consent must not ship.
- Private transcripts and raw audio stay out of identity JSON.
- Untrusted remote bytes are rehashed against descriptors; possession of a
  path is not integrity.
- GraphRAG evidence must be CID-bearing for the current turn; do not bind
  uncited slots.
- Agents must not escalate dry-run success to production publication authority.

## 14. Observability and operations

| Surface | What to log / retain |
| --- | --- |
| Normalize | counts in/out, quarantine reason histogram, quality report version |
| Materialize | workset_id, job specs (no credentials), TTS/ASR receipt digests |
| Local release | release_id, release_cid, row_counts, descriptor count, policy_digest |
| Dry-run | plan_digest, upload_bytes, estimated_cost_usd, skipped_exact_matches |
| Approval | approval_id, approver, max_cost_usd, max_upload_bytes (no tokens) |
| Commit | commit_sha, uploaded_paths, plan_digest |
| Verify | verified_file_count, verified_bytes, pinned redownload ok |
| Pointer | canary_percent, previous_release_id, status |
| Load | commit_sha, release_cid, index_cid, selected_shard_paths |

Operator knobs: `dataset_repo_id` (default `Publicus/211-abby-tts`), release
prefix template, pointer path, transfer/storage rate assumptions for cost
receipts, quality policy version, shard_rows / split salt in release policy.

## 15. Validation

```bash
test -s docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md && rg -n \
  'voice|Parquet|CID|dry-run|approval|revision|rollback|append-only' \
  docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md

# Implementation anchors (read-only checks)
rg -n 'class AbbyVoiceDatasetNormalizer|QuarantineReason|deterministic_split' \
  ipfs_datasets_py/voice/normalize.py
rg -n 'class AudioQualityPolicy|basis points|validate_tts_asr_roundtrip' \
  ipfs_datasets_py/voice/audio_quality.py
rg -n 'class SlottedResponseIndex|UnsafeSlotBindingError|graph_cid' \
  ipfs_datasets_py/voice/graphrag.py
rg -n 'byte-identical rebuild|sharded ZSTD Parquet|class AbbyVoiceHFReleaseBuilder' \
  ipfs_datasets_py/voice/hf_release.py
rg -n 'revision-pinned|immutable commit SHA|class AbbyVoiceReleaseLoader' \
  ipfs_datasets_py/voice/release_loader.py
rg -n 'write_zstd_parquet|FileDescriptor|reject_identity_contamination' \
  ipfs_datasets_py/huggingface/release.py
rg -n 'dry-run diff and cost receipt|append-only|canary_promote_pointer|rollback_pointer|autonomous work stops' \
  ipfs_datasets_py/huggingface/publisher.py
rg -n 'intentional aliases|HuggingFaceStaleCacheAliasError' \
  ipfs_datasets_py/huggingface/snapshot.py
```

**Limitations:** live Hub publish, live redownload, and live ASR round-trips
require provisioned network, secrets, and optional extras. Offline validation
of this guide is documentation completeness plus static path presence. A green
local Parquet rebuild is not a published release.

## 16. Related documentation

| Document | Relationship |
| --- | --- |
| [CONTENT_ADDRESSING_AND_IPLD.md](CONTENT_ADDRESSING_AND_IPLD.md) | CID profiles, digests, CAR |
| [STORAGE_CACHING_AND_BACKENDS.md](STORAGE_CACHING_AND_BACKENDS.md) | Pins, routers, caches |
| [P2P_AND_PUBLICATION.md](P2P_AND_PUBLICATION.md) | Distribution + thin HF publish surface |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Identifier ≠ location ≠ receipt |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional pyarrow / hf_hub / datasets |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Trust fail-closed vs feature degrade |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product placement of voice release contracts |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain flows |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Package ownership map |

## 17. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide for `ImmutableDatasetReleaseLifecycle@1` (IPFSDOC-025) from current `voice` and `huggingface` packages. |
