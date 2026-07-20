# ITP Hammer Replayable Receipts and IPFS-Aware Storage

Status: Implemented (HAMMER-012)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.receipts`
Tests: `tests/unit_tests/logic/hammers/test_receipts.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract this module only persists — never re-derives or
upgrades), `docs/logic/itp_hammer_corpus.md` (HAMMER-003, the
content-addressed premise corpus every `PremiseRecord` is drawn from),
`docs/logic/itp_hammer_provenance.md` (HAMMER-009, `NormalizedEvidence`),
and the HAMMER-010 reconstruction pipeline in `ipfs_datasets_py.logic.
hammers.reconstruction` (`ReconstructionEvidence`, the "checked source"
this module persists) and its HAMMER-011 recovery extension in
`ipfs_datasets_py.logic.hammers.fallbacks` (`DecompositionPlan`).

## 1. Purpose

Every earlier hammer stage produces its own versioned, content-addressed
record — `HammerRequest`, `PremiseRecord`, `TranslationRecord`,
`SolverAttemptRecord`, `ProofCandidateRecord`, `ReconstructionRecord`,
`EnvironmentLockRecord`, and the final `HammerResult` (HAMMER-001), plus
out-of-band evidence alongside several of them (`SolverAttemptEvidence`
from HAMMER-008, `NormalizedEvidence` from HAMMER-009,
`ReconstructionEvidence` from HAMMER-010, an optional `DecompositionPlan`
from HAMMER-011). None of that is, by itself, durably persisted anywhere,
bundled together, or addressed by content as a single unit — a
`HammerResult` only references digests (`raw_output_digest`,
`kernel_output_digest`, ...) of evidence that lives, if anywhere, in
whatever ephemeral process produced it.

> Persist canonical request, selected premises, translation artifacts,
> solver candidates, reconstruction sources, environment lock, and
> verification outcome with content digests or CIDs. Support local-disk
> fallback and redact private theorem sources, credentials, and raw
> prompts from publishable receipts.

`ipfs_datasets_py.logic.hammers.receipts` is that final, dedicated
persistence layer.

## 2. `HammerReceipt`: one coherent, replayable bundle

`HammerReceipt` bundles:

| Field | Source | What it carries |
| --- | --- | --- |
| `result` | HAMMER-001 | The canonical `HammerResult` — request, selected premises, translation artifacts, solver attempts, proof candidate, reconstruction, environment lock, and the final verification outcome. |
| `reconstruction_evidence` | HAMMER-010 | The full checked native source, the reconstructed tactic/term text, and the kernel's raw stdout/stderr/exit status — the "reconstruction sources" the taskboard entry names explicitly. |
| `solver_evidence` | HAMMER-008 | Zero or more `SolverAttemptEvidence`: exact argv, input digest, raw solver stdout/stderr, solver trace. |
| `normalized_evidence` | HAMMER-009 | Zero or more `NormalizedEvidence`: structural proof steps, unsat cores, models/counterexamples normalized from that raw solver output. |
| `decomposition_plan` | HAMMER-011 | An optional `DecompositionPlan`, if the run went through the failure-recovery pipeline. |
| `created_at`, `notes`, `metadata` | — | Non-authoritative bookkeeping. |

`receipt_id` is always a deterministic content digest (`compute_content_digest`, the same content-addressing function used throughout the pipeline since HAMMER-003) over every field above **except** `receipt_id` itself and the non-authoritative `created_at`/`notes`/`metadata` — two runs that produced byte-identical trust-contract content and evidence always resolve to the same receipt id, regardless of when they were persisted or what diagnostic notes were attached. `compute_receipt_digest()` recomputes it independently for integrity verification (`compute_receipt_digest(receipt) == receipt.receipt_id` should always hold for a normally-constructed receipt).

### 2.1 Coherence validation

`HammerReceipt.validate()` (called eagerly at construction, exactly like
`HammerResult`/`NormalizedEvidence`) re-runs `HammerResult.validate()` (so
the HAMMER-001 `VERIFIED` trust invariant is still fully enforced) and
additionally requires every piece of out-of-band evidence to reference the
*same* run as `result`:

- `reconstruction_evidence.request_id` must equal `result.request.request_id`; if `result.reconstruction`/`result.proof_candidate` are present, `reconstruction_evidence.reconstruction_id`/`candidate_id` must match theirs.
- Every `solver_evidence[i].attempt_id` must be one of `result.solver_attempts[*].attempt_id`.
- Every `normalized_evidence[i].request_id`/`attempt_id` must match `result`'s request and a known solver attempt.
- `decomposition_plan.request_id` (and, transitively, every one of its own subgoals' `request_id`, enforced by `DecompositionPlan.validate()` itself) must match `result.request.request_id`.

A receipt built from evidence belonging to two different runs raises
`ReceiptValidationError` — it can never silently mix them.

## 3. Publishable (redacted) view

`HammerReceipt.to_publishable_dict()` / the free function
`build_publishable_view()` build a new dictionary (the receipt and its
nested records are never mutated) safe to share publicly. Two independent
redaction passes run, in order:

### 3.1 Targeted redaction of private theorem content

Each of the following string fields, if present, is replaced with a
placeholder of the shape `<redacted:<label> length=<N> digest=<content
digest>>` — the length and a deterministic content digest are kept (so a
recipient can still verify a later-published full text matches, without
ever seeing it), the raw text never is:

| Field | Label |
| --- | --- |
| `result.request.goal_statement` | `private-theorem-goal` |
| Each `result.translations[i].translated_text` | `private-theorem-translation` |
| `result.proof_candidate.certificate` | `private-theorem-candidate-certificate` |
| `reconstruction_evidence.checked_source` | `private-theorem-checked-source` |
| `reconstruction_evidence.reconstructed_proof_text` | `private-theorem-proof-text` |
| `reconstruction_evidence.stdout` / `stderr` | `kernel-stdout` / `kernel-stderr` |
| Each `solver_evidence[i].raw_stdout` / `raw_stderr` / `solver_trace` | `solver-stdout` / `solver-stderr` / `solver-trace` |
| Each `normalized_evidence[i].proof_steps[j].formula` | `proof-step-formula` |
| Each `decomposition_plan.subgoals[i].statement` | `llm-suggested-subgoal` (LLM-sourced) or `private-theorem-subgoal` (native-structural) |

`PremiseRecord.statement` is **not** redacted: HAMMER-003's corpus model
only ever ingests theorems from a *declared*, licensed `CorpusSource` — the
premises a receipt references are already public, licensed corpus content,
unlike the caller's own private request goal.

An LLM-suggested decomposition subgoal's `redacted_suggestion` field
(HAMMER-011's own redaction gate — see `docs/logic/itp_hammer_failure_policy.md`
§3) is left untouched; it is the *only* subgoal text a publishable receipt
ever surfaces for that entry, since `statement` (the raw suggestion) is
itself redacted here.

### 3.2 Defense-in-depth credential scrubbing

After the targeted pass, the entire payload is walked recursively
(`scrub_credential_text`/`_scrub_tree`):

- Any dict key matching a sensitive-name pattern (`password`, `secret`,
  `api_key`/`apikey`, `access_key`, `private_key`, `authorization`,
  `token`, `credential`, `bearer`, case-insensitive) has its **entire
  value** replaced with `<redacted:credential>`, regardless of shape. This
  is what protects structured credential fields wherever they appear —
  caller `metadata`, `HammerRequest.metadata`, diagnostic `notes`, even an
  `EnvironmentLockRecord.executable_paths` entry someone accidentally named
  `api_token`.
- Every remaining string leaf is scanned for common credential *shapes*
  (AWS access key ids, GitHub/Slack/OpenAI-style tokens, bearer tokens,
  JWTs, PEM private-key blocks) and any match is replaced with the same
  placeholder — independent of which field it was found in, so a secret
  accidentally embedded in raw solver stdout or a kernel error message is
  still caught even though that string was already targeted-redacted in
  step 3.1 (belt and suspenders: the same placeholder machinery in 3.1
  already removes the entire raw text for those fields, so 3.2 mainly
  protects fields **not** covered by the table above, such as caller
  metadata and notes).

The result carries `"visibility": "publishable"`, a sorted
`"redaction_notes"` list of every label actually redacted, and a
`"publishable_digest"` — a content digest of the redacted payload itself,
computed before those two bookkeeping keys are added, so a recipient can
independently verify the published copy has not been altered after
publication.

A publishable payload is intentionally **not** reconstructed back into a
strict `HammerReceipt` — it is a lossy, redacted view. Only the full,
unredacted receipt is meant to be replayed.

## 4. `ReceiptStore`: IPFS-aware persistence with local-disk fallback

`ReceiptStore` is the physical persistence layer:

- Every `put()` call **always** writes the receipt's canonical JSON payload
  to a local, content-addressed disk cache under `root_dir` (default
  `~/.cache/ipfs_datasets_py/hammer_receipts`, overridable via
  `IPFS_DATASETS_PY_HAMMER_RECEIPTS_DIR`), split into `full/` (the
  unredacted, replayable receipt, keyed by `receipt_id`) and
  `publishable/` (the redacted view, written only when `publish=True`).
  This means the store is fully functional with **zero external
  dependencies** — the default constructor never even attempts to resolve
  an IPFS backend.
- Pushing the same bytes through
  `ipfs_datasets_py.ipfs_backend_router.get_ipfs_backend()` is **opt-in**
  (`use_ipfs=True`, the `IPFS_DATASETS_PY_HAMMER_RECEIPTS_USE_IPFS`
  environment variable, or an explicitly injected `ipfs_backend` — the
  last of which is how tests exercise the IPFS-aware path without any real
  daemon/network dependency) and always best-effort: any failure — no
  `ipfs` binary, no daemon running, no network, an unexpected backend
  error — is caught, logged, and the write proceeds to local disk as
  normal. `put()` never raises merely because IPFS is unavailable; it only
  raises `ReceiptStorageError` if *both* IPFS (when attempted) *and* the
  local-disk write fail.
- A lightweight local index (`<root_dir>/index.json`) records the CID (if
  any) each digest was last pushed to. If a local cache file is later
  deleted but the index survives, `get()`/`get_publishable()` can still
  recover the content from IPFS by CID and repopulate the local cache —
  this is the "durable IPFS-aware storage" half of the requirement, while
  the local cache file itself remains the first-choice, network-free read
  path.

### 4.1 API summary

```python
from ipfs_datasets_py.logic.hammers import receipts as rc

store = rc.ReceiptStore(root_dir="/var/lib/hammer-receipts")  # local-disk only, no IPFS
receipt = rc.HammerReceipt(result=hammer_result, reconstruction_evidence=evidence)

result = store.put(receipt, publish=True)
# result.full.backend in {"local-disk", "ipfs"}; result.full.digest == receipt.receipt_id
# result.publishable.digest == receipt.receipt_id (same lookup key, redacted content)

replayed = store.get(receipt.receipt_id)          # full HammerReceipt, replayable
published = store.get_publishable(receipt.receipt_id)  # redacted dict, for public sharing

store.exists(receipt.receipt_id)   # -> True
store.list_ids()                   # -> [receipt.receipt_id, ...]
```

`persist_hammer_receipt(receipt, store=None, publish=False)` is a thin
convenience wrapper that constructs a default `ReceiptStore()` when
`store` is omitted.

## 5. Why this never weakens the trust contract

- `HammerReceipt.validate()` re-runs `HammerResult.validate()` unmodified —
  the HAMMER-001 `VERIFIED` invariant (a `HammerResult` may only claim
  `VERIFIED` alongside a kernel-accepted `ReconstructionRecord`) is fully
  intact; this module only ever serializes/deserializes that already-valid
  record graph, never reconstructs or relaxes it.
- `receipt_id` is always computed from content, never accepted as an
  unverified caller-supplied label — two different runs can never
  collide into (or spoof) the same id, and a re-persisted, byte-identical
  run always resolves to the same one (deduplication for free).
- The publishable view is additive-only redaction: every targeted field is
  *replaced*, never silently dropped without a trace (the placeholder still
  records length and digest, and `redaction_notes` lists every label
  redacted) — a consumer can tell exactly what was withheld and why, and
  independently verify the private content later if given access to it,
  without the publishable copy itself ever having revealed it.
- IPFS failures degrade to local disk silently and are never conflated with
  "the receipt does not exist" — `ReceiptNotFoundError` is only raised when
  neither the local cache nor a resolvable IPFS backend has the requested
  digest.

## 6. Schema summary

| Type | Purpose |
| --- | --- |
| `HammerReceipt` | The full, replayable bundle: `HammerResult` plus out-of-band evidence, content-addressed by `receipt_id`. |
| `StorageLocation` | Where one persisted payload physically lives: `backend` (`"ipfs"`/`"local-disk"`), `digest`, `cid`, `path`, `pinned`. |
| `PersistResult` | The result of one `ReceiptStore.put()` call: `full` and (if `publish=True`) `publishable` `StorageLocation`s. |
| `ReceiptStore` | IPFS-aware, content-addressed persistence with a local-disk fallback and a CID-recovery index. |
| `ReceiptError` / `ReceiptValidationError` / `ReceiptStorageError` / `ReceiptNotFoundError` | Error hierarchy: invalid receipt content, storage failure (both backends failed), and lookup miss, respectively. |

## 7. Worked example

```python
from ipfs_datasets_py.logic.hammers import receipts as rc
from ipfs_datasets_py.logic.hammers.models import HammerResult

# result, reconstruction_evidence, solver_evidence, normalized_evidence
# come from the earlier HAMMER-001/008/009/010 pipeline stages.
receipt = rc.HammerReceipt(
    result=result,
    reconstruction_evidence=reconstruction_evidence,
    solver_evidence=solver_evidence,
    normalized_evidence=normalized_evidence,
)

store = rc.ReceiptStore()  # local-disk by default; safe with zero setup
persisted = store.put(receipt, publish=True)

print(persisted.full.digest)          # == receipt.receipt_id
print(persisted.full.backend)         # "local-disk" unless IPFS was opted in and reachable

# Later, potentially in a different process:
replayed = store.get(receipt.receipt_id)
assert replayed.receipt_id == receipt.receipt_id
assert replayed.is_verified() == receipt.is_verified()

published = store.get_publishable(receipt.receipt_id)
assert published["visibility"] == "publishable"
```
