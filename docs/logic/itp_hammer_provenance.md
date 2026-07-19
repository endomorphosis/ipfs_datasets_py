# ITP Hammer Normalized Proof-Trace and Counterexample Evidence

Status: Implemented (HAMMER-009)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.provenance`
Tests: `tests/unit_tests/logic/hammers/test_provenance.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract whose `HammerResultStatus`/`ProofCandidateRecord` this
module produces evidence for), `docs/logic/itp_hammer_translation.md`-style
translation map produced by HAMMER-007's `ipfs_datasets_py.logic.hammers.
translation` module (cross-referenced here), and the HAMMER-008 solver
portfolio in `ipfs_datasets_py.logic.hammers.portfolio` (the source of the
raw evidence this module normalizes).

## 1. Purpose

HAMMER-008's solver portfolio produces an untrusted
`SolverAttemptRecord` (a raw `SolverVerdict` plus a digest of the solver's
output) and out-of-band `SolverAttemptEvidence` (the literal stdout/stderr
text) for every attempt. That raw text is solver- and format-specific: a
Vampire/E TSTP derivation listing full of clause names and inference
annotations, a Z3/CVC5 `sat`/`unsat`/`unknown` response, an SMT-LIB
unsat-core response, or a model/countermodel s-expression. None of it is
directly comparable across solvers, and none of it is safe to hand to a
downstream consumer (a receipt, a reconstruction attempt, a human auditor)
without first being normalized into a single, uniform shape.

This module is that normalization layer. It turns raw solver text into a
single `NormalizedEvidence` record that is:

- **Content-addressed** — `NormalizedEvidence.content_digest` (and
  `evidence_id`, which is always equal to it) is a deterministic digest over
  every other field, computed with the same `compute_content_digest` used
  throughout the rest of the hammer pipeline (HAMMER-003/007/008).
- **Structurally decomposed, never semantically reinterpreted** — a TSTP
  proof becomes a list of `ProofStep`s (id, role, inference rule, parent
  ids, and an original premise label when the solver's `file(...)`
  annotation carries one), never a re-parsed logical formula. This module
  does not need to understand what a formula *means* to normalize it.
- **Traceable back to premises and the translation map** — every
  `NormalizedEvidence` preserves the caller-supplied `premise_ids` and
  `translation_ids` verbatim, and cross-references any identifier it finds
  in the trace against those premise ids (`NormalizedUnsatCore.
  matched_premise_ids`) and against a HAMMER-007 `TranslationMap`
  (`translation_map_refs`) — using only exact string matches, never a fuzzy
  or inferred correspondence.
- **Fail-closed by construction** — `NormalizedEvidence.
  recommended_status` can only ever be `HammerResultStatus.CANDIDATE`,
  `COUNTEREXAMPLE`, or `UNKNOWN`. Constructing one with any other status
  (in particular `VERIFIED`) raises `ValueError` immediately, in
  `__post_init__`, exactly like `HammerResult`'s own trust-boundary
  invariant (HAMMER-001).

## 2. The trust boundary this module enforces

> A malformed, absent, or unsupported trace results in `candidate` or
> `unknown`, never `verified`.

This is enforced two ways:

1. **Structurally, by `NormalizedEvidence.validate()`.** The
   `recommended_status` field is checked against
   `ALLOWED_RECOMMENDED_STATUSES = {CANDIDATE, COUNTEREXAMPLE, UNKNOWN}` on
   every construction (via `__post_init__`, so it cannot be bypassed by
   skipping a call to `validate()`). There is no code path in this module
   that can produce `HammerResultStatus.VERIFIED` — the value is never even
   referenced in a return statement. Only a HAMMER-010
   `ReconstructionRecord` with `kernel_accepted=True` may promote a run to
   `VERIFIED`, and that is enforced by `HammerResult` itself.
2. **By the normalization decision table below**, which always resolves a
   malformed, absent, or unsupported trace to `CANDIDATE` (a claim exists,
   nothing verifiable backs it yet) or `UNKNOWN` (nothing usable at all) —
   never to `COUNTEREXAMPLE` either, since that status requires an actually
   parsed countermodel (see §4).

## 3. `EvidenceKind`: what was normalized

| Kind | Meaning |
| --- | --- |
| `proof` | A structurally parsed TSTP/TPTP derivation listing (`proof_steps` populated; `unsat_core` derived from its leaf steps). |
| `unsat_core` | A parsed SMT-LIB `(get-unsat-core)`-style flat identifier list (`unsat_core` populated; no per-step derivation available). |
| `model` | A parsed satisfying assignment for a `SAT` verdict (`model` populated). |
| `counterexample` | A parsed countermodel for a `DISPROVED` (TPTP `CounterSatisfiable`) verdict (`model` populated). |
| `absent` | A conclusive verdict (`PROVED`/`UNSAT`/`SAT`/`DISPROVED`) was reported but no parseable trace text was available, or a genuinely inconclusive verdict (`UNKNOWN`/`TIMEOUT`/`ERROR`) was reported at all. |
| `malformed` | Trace text was present but failed a basic structural well-formedness check (unbalanced parentheses, a missing terminating `.`, too few TSTP fields). `malformed_reason` is always set. |
| `unsupported` | The evidence format is not one this module can structurally parse (anything other than `"tstp"`/`"smtlib"`, e.g. `"lfsc"`, `"alethe"`, or an unset format). `malformed_reason` is always set. |

## 4. Normalization decision table

Every `SolverVerdict` is classified into exactly one of four buckets
(enforced by a module-level `assert` that runs at import time, so adding a
new `SolverVerdict` member without updating this module fails loudly rather
than silently misclassifying it):

| Verdict bucket | Members | Meaning |
| --- | --- | --- |
| Proof-claiming | `PROVED`, `UNSAT` | The solver claims a refutation/proof exists. |
| Model-claiming | `SAT` | The solver claims a satisfying assignment exists. |
| Counterexample-claiming | `DISPROVED` | The solver claims a countermodel to a TPTP conjecture exists (`CounterSatisfiable`). |
| Inconclusive | `UNKNOWN`, `TIMEOUT`, `ERROR` | No conclusive claim at all. |

Given a verdict bucket and the raw trace text:

1. **Inconclusive verdict** → always `kind=absent`, `recommended_status=
   UNKNOWN`, regardless of any trace text (there is nothing conclusive to
   normalize even if stray text happens to be present).
2. **Unsupported format** (attempt/certificate format is not `"tstp"`/
   `"smtlib"`) → always `kind=unsupported`, `recommended_status=UNKNOWN`.
3. **Empty/whitespace-only trace text**, for any conclusive verdict →
   `kind=absent`, `recommended_status=CANDIDATE`. This never becomes
   `COUNTEREXAMPLE`, even for a `DISPROVED` verdict — `EvidenceKind.
   COUNTEREXAMPLE` is reserved for an actually-normalized countermodel (see
   `NormalizedEvidence.validate`'s `COUNTEREXAMPLE` invariant in §5), so an
   absent countermodel is still just an unverified `CANDIDATE` claim.
4. **Proof-claiming verdict with trace text**:
   - TSTP: parsed via `parse_tstp_proof`. A parse failure (unbalanced
     parens, missing `.`, too few fields) → `kind=malformed`,
     `recommended_status=UNKNOWN`. No statements found at all → `kind=
     absent`, `recommended_status=CANDIDATE`. Otherwise → `kind=proof`,
     `proof_steps` populated, `unsat_core` derived via
     `unsat_core_from_proof_steps`, `recommended_status=CANDIDATE`.
   - SMT-LIB: parsed via `parse_smtlib_unsat_core`. Unbalanced
     s-expression → `kind=malformed`/`UNKNOWN`. No flat identifier list
     found → `kind=absent`/`CANDIDATE`. Otherwise → `kind=unsat_core`,
     `recommended_status=CANDIDATE`.
5. **Model/counterexample-claiming verdict with trace text**: parsed via
   `parse_tptp_model` or `parse_smtlib_model`. Unbalanced/malformed →
   `kind=malformed`/`UNKNOWN`. Nothing recognizable found → `kind=absent`/
   `CANDIDATE`. Otherwise → `kind=model` (for `SAT`) or
   `kind=counterexample` (for `DISPROVED`), with
   `recommended_status=CANDIDATE` or `COUNTEREXAMPLE` respectively.

## 5. `NormalizedEvidence`

```python
@dataclass
class NormalizedEvidence:
    schema_version: str
    evidence_id: str                     # == content_digest
    request_id: str
    attempt_id: str
    candidate_id: Optional[str]
    kind: str                            # an EvidenceKind value
    format: str                          # "tstp" | "smtlib" | "unknown" | <unsupported format>
    verdict: SolverVerdict
    premise_ids: List[str]               # verbatim caller input
    translation_ids: List[str]           # verbatim caller input
    translation_map_refs: List[TranslationMapEntry]
    proof_steps: List[ProofStep]
    unsat_core: Optional[NormalizedUnsatCore]
    model: Optional[NormalizedModel]
    raw_trace_digest: Optional[str]
    malformed_reason: Optional[str]
    recommended_status: HammerResultStatus  # CANDIDATE | COUNTEREXAMPLE | UNKNOWN only
    content_digest: str
```

Validation invariants (checked eagerly in `__post_init__`, exactly like
`HammerResult`):

- `recommended_status` must be one of `ALLOWED_RECOMMENDED_STATUSES`.
- `kind` must be a known `EvidenceKind` value.
- `kind in (malformed, unsupported)` requires a non-empty
  `malformed_reason`.
- `kind == counterexample` iff `recommended_status == COUNTEREXAMPLE` (the
  two imply each other — you cannot have one without the other).
- `premise_ids`/`translation_ids` must be lists of non-empty strings;
  `translation_map_refs` must contain `TranslationMapEntry`; `proof_steps`
  must contain `ProofStep`; `unsat_core`/`model`, when present, must be the
  matching normalized type.

`content_digest` (and `evidence_id`, always equal to it) is computed once,
lazily, over every other field via `compute_content_digest` — the same
canonical-JSON-then-SHA-256 (optionally CIDv1) digest function used by the
corpus (HAMMER-003) and portfolio (HAMMER-008) modules. Two
`NormalizedEvidence` instances built from byte-identical inputs always
produce the same digest; `to_dict()`/`from_dict()` round-trip losslessly
and preserve it.

### `ProofStep`

| Field | Meaning |
| --- | --- |
| `step_id` | The solver-assigned clause/formula name (e.g. `"f4"`). |
| `role` | The TPTP role (`"axiom"`, `"plain"`, `"negated_conjecture"`, ...). |
| `rule` | The inference rule name from an `inference(rule, ...)` annotation; `None` for a leaf/input step. |
| `formula` | The raw formula text, kept as opaque text. |
| `parent_ids` | Step ids cited as parents by an `inference(...)` annotation. |
| `source_name` | The original input label from a `file('src', name)` annotation, when present. |

### `NormalizedUnsatCore`

`core_ids` — the leaf (`rule is None`) step identifiers of a TSTP proof
(preferring `source_name` over `step_id`), or the flat token list of an
SMT-LIB unsat-core response. `matched_premise_ids` — the subset of a
caller-supplied `premise_ids` list that exactly matches an entry in
`core_ids`.

### `NormalizedModel` / `ModelBinding`

`NormalizedModel.bindings` is a list of `ModelBinding(symbol, value,
source_name)`: `symbol` is the target-format name as printed by the solver,
`value` is the raw printed value/definition (kept as opaque text), and
`source_name` is the original source-level name resolved via a
`TranslationMap` reverse lookup, when a match is found.

## 6. TSTP/TPTP structural parsing (`parse_tstp_proof`)

`parse_tstp_proof` scans raw text for `cnf(`/`fof(`/`tff(` statements using
a paren/quote-depth-aware scanner (`_find_matching_paren`), splits each
statement's argument list on **top-level** commas only
(`_split_top_level`, so a formula body's own commas/brackets never
fragment a statement), and interprets the (optional) fourth argument as an
annotation:

- `file('src', name)` → a leaf/input step; `rule=None`, `source_name=name`.
- `inference(rule, info, [p1, p2, ...])` → a derived step; `rule` and
  `parent_ids` extracted from the bracketed parent list.
- Anything else recognizable (`introduced(...)`) or not is preserved as an
  opaque `rule` string rather than discarded.

No statements found at all is reported as `(steps=[], reason=None)` — an
*absent* trace, not malformed. Unbalanced parentheses or a missing
terminating `.` is reported as `(steps=[], reason=<description>)` — the
*malformed* case. `unsat_core_from_proof_steps` then derives the used
premises: a TSTP derivation listing only ever contains clauses the solver
actually used, so every un-derived (leaf) step is, by construction, part of
the core.

`parse_tptp_model` reuses the same scanner for a TPTP finite-model/
countermodel listing (emitted with the same clause syntax under roles like
`fi_domain`/`fi_functors`/`fi_predicates`), reinterpreting each step as one
`ModelBinding` whose value is the clause's own formula text.

## 7. SMT-LIB s-expression parsing

`parse_all_sexprs` is a minimal, dependency-free s-expression tokenizer/
parser (atoms, quoted strings, and arbitrarily nested `(...)` lists) that
raises `ValueError` for unbalanced parentheses — the single failure mode
this module maps to `EvidenceKind.MALFORMED`.

- `parse_smtlib_unsat_core` looks for a flat top-level list of atoms (the
  literal shape of a `(get-unsat-core)` response, e.g. `(a1 a2 a3)`).
- `parse_smtlib_model` recognizes three shapes: a `(model (define-fun ...)
  ...)` wrapper, a bare top-level list of `(define-fun ...)` forms without
  the `model` wrapper, and a `((name value) ...)` list as printed by
  `(get-value (...))`.

## 8. Entry points

```python
def normalize_solver_evidence(
    *, request_id: str, attempt: SolverAttemptRecord,
    evidence: Optional[SolverAttemptEvidence] = None,
    raw_stdout: str = "", raw_stderr: str = "",
    premise_ids: Sequence[str] = (), translation_ids: Optional[Sequence[str]] = None,
    translation_map: Optional[TranslationMap] = None, candidate_id: Optional[str] = None,
) -> NormalizedEvidence: ...

def normalize_certificate(
    *, request_id: str, attempt_id: str, verdict: SolverVerdict,
    certificate: Optional[str], certificate_format: Optional[str],
    premise_ids: Sequence[str] = (), translation_ids: Sequence[str] = (),
    translation_map: Optional[TranslationMap] = None, candidate_id: Optional[str] = None,
) -> NormalizedEvidence: ...

def normalize_portfolio_run(
    run_result: PortfolioRunResult, *, request_id: Optional[str] = None,
    premise_ids: Sequence[str] = (), translation_map: Optional[TranslationMap] = None,
) -> Dict[str, NormalizedEvidence]: ...

def build_proof_candidate_record(
    normalized: NormalizedEvidence, *, candidate_id: str, request_id: str,
    solver_attempt_id: str, certificate: Optional[str] = None,
    certificate_format: Optional[str] = None,
) -> ProofCandidateRecord: ...

def aggregate_recommended_status(evidences: Iterable[NormalizedEvidence]) -> HammerResultStatus: ...
```

- **`normalize_solver_evidence`** is the primary integration point for a
  live HAMMER-008 portfolio run: it takes a `SolverAttemptRecord` (whose
  `target` selects the TPTP/SMT-LIB parser and whose `verdict` selects the
  decision-table branch) and either a `SolverAttemptEvidence` (preferred) or
  raw `raw_stdout`/`raw_stderr` strings.
- **`normalize_certificate`** normalizes a standalone certificate string —
  e.g. a previously persisted `ProofCandidateRecord.certificate` — rather
  than a live attempt's stdout/stderr. Any `certificate_format` other than
  `"tstp"`/`"smtlib"` (including `None`) always resolves to `unsupported`/
  `UNKNOWN`, since this module has no structural parser for other
  certificate formats (e.g. LFSC, Alethe) and refuses to guess.
- **`normalize_portfolio_run`** batch-normalizes every attempt in a
  `PortfolioRunResult`, returning a `Dict[attempt_id, NormalizedEvidence]`.
- **`build_proof_candidate_record`** builds an untrusted
  `ProofCandidateRecord` (HAMMER-001) from `CANDIDATE`-recommending
  evidence, preferring `unsat_core.matched_premise_ids` over the full
  `premise_ids` when a core was parsed. It raises `MalformedEvidenceError`
  (a `ValueError` subclass reserved for API misuse, never for a malformed
  *solver* trace) if asked to build a candidate from evidence that only
  recommends `COUNTEREXAMPLE` or `UNKNOWN` — a `ProofCandidateRecord`
  specifically means "an untrusted candidate *proof*", not a countermodel.
- **`aggregate_recommended_status`** picks the single most informative
  status across several normalized attempts, preferring `CANDIDATE` >
  `COUNTEREXAMPLE` > `UNKNOWN`, returning `UNKNOWN` for an empty input.

## 9. What this module deliberately does not do

- It does not run a solver or a kernel — it only interprets output already
  produced by HAMMER-008's portfolio.
- It does not attempt semantic understanding of a proof's formula bodies —
  only structural decomposition (ids, roles, rules, parent references).
- It does not fabricate a premise or translation-map correspondence: every
  cross-reference is an exact string match against caller-supplied data,
  and an unmatched identifier is simply left unresolved.
- It cannot promote a result to `VERIFIED` under any circumstance — see §2.
  That is exclusively HAMMER-010's job, gated on an actual target-ITP
  kernel accepting a reconstructed proof.
