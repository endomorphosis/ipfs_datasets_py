# ITP Hammer User Guide

Status: Implemented (HAMMER-015)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.*`
CLI: `scripts/cli/logic_cli.py` (`hammer-*` subcommands)
MCP: `ipfs_datasets_py.mcp_server.tools.logic_hammer`
Benchmark: `benchmarks/bench_itp_hammer.py`
Release gate: `scripts/ops/logic/release_itp_hammer_gate.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract), `docs/logic/itp_hammer_capability_inventory.md`
(HAMMER-002), `docs/logic/itp_hammer_corpus.md` (HAMMER-003),
`docs/logic/itp_hammer_premise_selection.md` /
`docs/logic/itp_hammer_learned_selection.md` (HAMMER-004/005),
`docs/logic/itp_hammer_provenance.md` (HAMMER-009),
`docs/logic/itp_hammer_failure_policy.md` (HAMMER-011),
`docs/logic/itp_hammer_receipts.md` (HAMMER-012),
`docs/logic/itp_hammer_mcp_contract.md` (HAMMER-013), and
`docs/logic/itp_hammer_security_model.md` (this task's companion
document, HAMMER-015).

## 1. What this pipeline is (and is not)

The ITP hammer pipeline selects premises for a goal, translates supported
goal fragments to TPTP or SMT-LIB, runs a bounded, policy-controlled
external solver portfolio, and — **only if a solver produces a
candidate** — attempts to reconstruct a native tactic/term proof and
independently check it with the target Interactive Theorem Prover's own
kernel.

It is **not** a claim that Lean, Coq/Rocq, Isabelle/HOL, and first-order
ATP/SMT logics are interchangeable. Each ITP has its own frontend
(HAMMER-006) and reconstructor (HAMMER-010); a solver's `sat`, `unsat`, or
`proved` response is always an **untrusted candidate**, never a theorem, until
the originating ITP's kernel accepts a reconstructed native proof under a
pinned environment. This is the single invariant every other feature in
this guide is built around — see `docs/logic/itp_hammer_contract.md` and
§3.4 below for how it is enforced in code, not just in prose.

## 2. Supported ITP/solver fragments

### 2.1 Interactive Theorem Provers (native frontend + reconstructor)

| ITP | Frontend adapter | Reconstructor | Notes |
|---|---|---|---|
| Lean 4 | `ipfs_datasets_py.logic.hammers.frontends.lean.LeanFrontend` | `ipfs_datasets_py.logic.hammers.reconstructors.lean.LeanReconstructor` | Also backs the HAMMER-011 native-automation fallback (`rfl`/`decide`/`simp_all`/`assumption`). |
| Coq/Rocq | `ipfs_datasets_py.logic.hammers.frontends.coq.CoqFrontend` | `ipfs_datasets_py.logic.hammers.reconstructors.coq.CoqReconstructor` | Invoked via `coqtop`. |
| Isabelle/HOL | `ipfs_datasets_py.logic.hammers.frontends.isabelle.IsabelleFrontend` | `ipfs_datasets_py.logic.hammers.reconstructors.isabelle.IsabelleReconstructor` | Reports a structured `unavailable` capability state where the local Isabelle toolchain is absent — see HAMMER-002's probe. |

Adding a fourth ITP requires a matching frontend *and* reconstructor
adapter; there is no generic "plain text" ITP stand-in anywhere in this
pipeline (HAMMER-006's acceptance criterion).

### 2.2 Untrusted external solvers (translation targets: TPTP, SMT-LIB)

| Solver | Format | Allow-listed by default? |
|---|---|---|
| Vampire | TPTP | No — every solver requires an explicit operator opt-in via `HammerPolicy.allowed_solvers` |
| E (eprover) | TPTP | No |
| Z3 | SMT-LIB | No |
| CVC5 | SMT-LIB | No |

`ipfs_datasets_py.logic.hammers.policy.known_solver_names()` is the
authoritative allow-list ceiling — an operator's `HammerPolicy.
allowed_solvers` must be a subset of it, and an empty list (the default)
means **no external solver runs at all**: translation-only / dry-run
policy. Run `scripts/ops/logic/probe_itp_hammer_environment.py` to see
which of these are actually installed in a given environment without
invoking any of them (HAMMER-002).

### 2.3 Supported logical fragments (translation)

`ipfs_datasets_py.logic.hammers.translation` lowers only an explicit,
first-order-safe fragment: monomorphic first-order formulas built from
`Const`/`Var`/`App`/`Eq`/`Not`/`And`/`Or`/`Implies`/`Forall`/`Exists` over
finite sort signatures, through explicit monomorphization and lambda
lifting/elimination. **Unsupported constructs — dependent types,
higher-order quantification over predicates, polymorphic type variables
left unresolved, or opaque/uninterpreted term forms the translator does
not recognize — fail closed with an explicit `unsupported_translation`
result.** They are never silently dropped, coerced, or approximated; see
`tests/unit_tests/logic/hammers/test_translation.py`'s negative fixtures
and `tests/integration/logic/hammers/test_adversarial_hammer.py` for the
adversarial suite that specifically tries to defeat this.

## 3. Using the pipeline

### 3.1 Python

```python
from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, ITPKind
from ipfs_datasets_py.logic.hammers.premise_selection import (
    GoalFeatures, select_premises,
)

manifest = CorpusManifest(manifest_id="my-corpus")
manifest.register_source(CorpusSource(
    corpus_id="my-corpus", name="My Corpus", source_itp=ITPKind.LEAN,
    version_ref="v1", license_id="Apache-2.0",
))
manifest.add_theorem(theorem_id="t1", corpus_id="my-corpus",
                      statement="theorem t1 : 1 + 1 = 2", imports=["Init"])

goal = GoalFeatures.from_statement("theorem goal : 1 + 1 = 2", imports=["Init"])
selection = select_premises(manifest, goal, top_k=8)
```

From there, `ipfs_datasets_py.logic.hammers.translation.TranslationContext`
lowers a structured goal/premise term to TPTP or SMT-LIB;
`ipfs_datasets_py.logic.hammers.portfolio.SolverPortfolio` runs the
policy-controlled solver portfolio; `ipfs_datasets_py.logic.hammers.
provenance.normalize_solver_evidence` and `build_proof_candidate_record`
normalize the raw solver output into an untrusted candidate;
`ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor`
subclasses reconstruct and kernel-check a candidate; and
`ipfs_datasets_py.logic.hammers.receipts.HammerReceipt`/`ReceiptStore`
persist the whole run. See `tests/integration/logic/hammers/
_golden_helpers.py` for fully worked, real (non-mocked) examples of every
stage wired together, including two genuine kernel invocations.

### 3.2 CLI (`scripts/cli/logic_cli.py`)

| Subcommand | What it does |
|---|---|
| `hammer-inspect` | Capture a native ITP goal snapshot (HAMMER-006). Requires `--confirm` to actually launch `lean`/`coqtop`/`isabelle`. |
| `hammer-select-premises` | Rank premises from a corpus manifest (HAMMER-004). Pure computation, no `--confirm` needed. |
| `hammer-translate` | Lower a goal/premise term to TPTP or SMT-LIB (HAMMER-007). Pure computation. |
| `hammer-run-candidate` | Run the policy-controlled solver portfolio (HAMMER-008/009). Requires `--confirm` to launch external solver processes. |
| `hammer-reconstruct` | Reconstruct and kernel-check a candidate proof (HAMMER-010). Requires `--confirm` to launch the native ITP kernel. |
| `hammer-retrieve-receipt` / `hammer-persist-receipt` | Fetch/persist a `HammerReceipt` (HAMMER-012). |
| `hammer-capability-status` | Report structured ITP/solver capability evidence with zero mandatory subprocess calls (`--no-probe-versions` for a fully hermetic probe). |

Example — a hermetic capability check, then a governed premise selection:

```bash
python scripts/cli/logic_cli.py hammer-capability-status --no-probe-versions
python scripts/cli/logic_cli.py hammer-select-premises \
    --goal-statement "theorem goal : 1 + 1 = 2" \
    --corpus-manifest-file my_corpus.json --top-k 8
```

Every operation that would spawn a real `lean`/`coqtop`/`isabelle`/solver
process (`hammer-inspect`, `hammer-run-candidate`, `hammer-reconstruct`)
refuses to do so without an explicit `--confirm` flag — see
`docs/logic/itp_hammer_security_model.md` §3 for the full rationale.

### 3.3 MCP (`ipfs_datasets_py.mcp_server.tools.logic_hammer`)

The same seven operations (`inspect`, `select-premises`, `translate`,
`run-candidate`, `reconstruct`, `retrieve-receipt`, `capability-status`)
are exposed as governed, async MCP tools with a correlation id threaded
through every response envelope. See `docs/logic/itp_hammer_mcp_contract.md`
for the full request/response schema and governance model.

### 3.4 The trust boundary in practice

No matter which of the three interfaces above is used, a result can only
ever reach `HammerResultStatus.VERIFIED` through one path: a
`ReconstructionRecord` with `kernel_accepted=True`, produced by an actual
subprocess invocation of the target ITP's own kernel/checker against a
reconstructed native proof. This is enforced at construction time by
`HammerResult.__post_init__` (see `ipfs_datasets_py.logic.hammers.models`)
— it is not merely a documented convention, and `scripts/ops/logic/
release_itp_hammer_gate.py` independently re-verifies it again for every
receipt a release references (see §7 and the security model doc).

## 4. Benchmark methodology (`benchmarks/bench_itp_hammer.py`)

```bash
PYTHONPATH=. python benchmarks/bench_itp_hammer.py \
    --fixture tests/fixtures/logic/hammers \
    --out data/logic/itp_hammer/benchmark.json
```

The benchmark has two parts, both run against the same fixture corpus
(`tests/fixtures/logic/hammers/golden_corpus.json`) so their corpus
revision always matches:

1. **Premise-selection recall/latency** — for every theorem `T` in the
   corpus, held-out from its own candidate pool, the deterministic
   HAMMER-004 baseline selector (the only selector enabled by default —
   see HAMMER-005's opt-in learned selector in
   `benchmarks/bench_itp_hammer_premise_selection.py` for a comparison
   against a pinned learned/graph-based alternative) is scored against an
   import-overlap proxy "relevant" set (`ipfs_datasets_py.logic.hammers.
   learned_selector.relevant_theorem_ids_by_import_overlap`) via
   recall@k and reciprocal rank, with per-call wall-clock latency.
2. **Whole-pipeline case latency and verification outcome** — one golden
   case per `HammerResultStatus` value the pipeline can produce
   (`verified` ×3 via Lean, Coq, and the native-automation fallback;
   `candidate`; `counterexample`; `timeout`; `unsupported_translation`;
   `unavailable`), built via the same shared builder functions
   `tests/integration/logic/hammers/test_end_to_end_hammer.py`
   (HAMMER-014) uses, timed end to end. A `verified` case's timing
   genuinely includes a real Lean/Coq kernel subprocess invocation; a
   case whose target kernel is not installed in the current environment
   is reported as `environment_unavailable` (an explicit capability gap,
   never fabricated).

The output additionally embeds the **resource defaults** in force
(`HammerPolicy`/`PortfolioPolicy` field defaults, read directly from the
dataclasses so this can never drift from the enforced values) and an
**environment capability snapshot** (from `data/logic/itp_hammer/
environment.json`, HAMMER-002), plus **reproducibility metadata**
(Python/platform version, corpus revision, generation timestamp).

Recall/latency semantics: recall@k and reciprocal rank use a
ground-truth-free *proxy* relevant set (theorems sharing at least one
import with the held-out theorem) because the fixture corpus does not
carry an explicit theorem-to-theorem dependency graph — this is a
methodology limitation, not a claim of ground-truth mathematical
relevance; see §6 for how this interacts with reproducibility.

## 5. Resource defaults

| Budget | Default | Enforced by |
|---|---|---|
| Per-attempt wall-clock timeout | 30 seconds (`HammerPolicy.timeout_seconds`) | Subprocess wall-clock deadline |
| Per-attempt CPU-time budget | Unset (`HammerPolicy.cpu_seconds = None`) | `RLIMIT_CPU` (POSIX) when set |
| Per-attempt memory budget | Unset (`HammerPolicy.memory_mb = None`) | `RLIMIT_AS` (POSIX) when set |
| Network access | Disabled (`HammerPolicy.network_allowed = False`) | Policy check before any solver/kernel launch |
| Allow-listed solvers | Empty (`HammerPolicy.allowed_solvers = []`) — no external solver runs by default | `PortfolioPolicy.validate()` |
| Max premises per request | 64 (`HammerPolicy.max_premises`) | `select_premises`/`select_premises_for_theorem` |
| Learned premise selector | Disabled (`HammerPolicy.allow_learned_premise_selector = False`) | HAMMER-005 gating |
| LLM premise ranking / decomposition hints | Disabled | HAMMER-011 gating |
| Native automation fallback | Disabled (`HammerPolicy.allow_native_automation_fallback = False`) | HAMMER-011 gating; must be explicitly opted in per-request |
| Max parallel solver processes | 4 (`PortfolioPolicy.max_parallel_processes`) | `SolverPortfolio` executor |
| Cancellation policy | Cancel remaining attempts on first conclusive verdict (`PortfolioPolicy.cancel_on_first_conclusive = True`) | `SolverPortfolio` executor |

Operators needing looser or tighter budgets construct an explicit
`HammerPolicy`/`PortfolioPolicy` — nothing here is hard-coded outside
those two records (see `docs/logic/itp_hammer_security_model.md` §2 for
why this matters).

## 6. Reproducibility requirements

A release (see §7) must be reproducible from three pinned artifacts:

1. **Corpus lock** (HAMMER-003): a content-derived `CorpusManifest.
   revision` — a pure function of registered corpus sources and ingested
   theorem entries. Two runs against byte-identical corpus content always
   produce the same revision.
2. **Environment lock** (HAMMER-002, `data/logic/itp_hammer/
   environment.json`): exact executable paths, versions, and
   available/unavailable status for every ITP/solver surface, captured
   without installing or invoking a solver's proof-search entry point.
3. **Receipts** (HAMMER-012): every `HammerReceipt.receipt_id` is a
   deterministic content digest over the full trust-contract record graph
   (excluding non-authoritative `created_at`/`notes`/`metadata`) — two
   byte-identical runs always resolve to the same receipt id, and
   `compute_receipt_digest(receipt) == receipt.receipt_id` is an
   independently checkable tamper-evidence property (re-verified by the
   release gate; see §7).

A genuine kernel subprocess invocation's own wall-clock timing is, by
nature, **not** reproducible bit-for-bit across hosts/runs — only its
pass/fail *outcome* and the digests of its inputs/outputs are asserted
stable. `data/logic/itp_hammer/golden-report.json` documents exactly
which fields are asserted reproducible for which case kind
(`"deterministic"` vs. `"real_kernel"`).

Every artifact above additionally carries a `generated_at` timestamp and
a documented freshness budget (`--max-receipt-age-days`,
`--max-environment-lock-age-days`, `--max-benchmark-age-days` on the
release gate) — reproducibility is treated as a property that must be
re-demonstrated periodically, not asserted once and assumed to hold
forever as toolchains and dependencies drift.

## 7. Release gate (`scripts/ops/logic/release_itp_hammer_gate.py`)

```bash
# Validate an existing evidence file (this is what CI/the taskboard runs):
PYTHONPATH=. python scripts/ops/logic/release_itp_hammer_gate.py \
    --evidence data/logic/itp_hammer/release-evidence.json

# (Re)generate the evidence file and its backing receipt store:
PYTHONPATH=. python scripts/ops/logic/release_itp_hammer_gate.py \
    --evidence data/logic/itp_hammer/release-evidence.json --generate
```

The gate **fails closed**: any missing file, parse error, stale artifact,
un-loadable/tampered receipt, or `verified` result lacking an actual
kernel-acceptance record causes a non-zero exit and a structured JSON
failure report — never a silent pass. See
`docs/logic/itp_hammer_security_model.md` §6 for the full list of checks
and the specific fail-closed conditions the taskboard's acceptance
criteria call out (missing corpus/environment locks, absent kernel proof,
stale receipts, verified-without-kernel-acceptance).

## 8. Privacy policy

- A hammer receipt's **full** form (`HammerReceipt.to_dict()`) contains
  the caller's private theorem/goal text, translated formula text,
  reconstructed native source, and raw solver/kernel stdout/stderr. It is
  intended for the operator's own replay/audit use and is **not**
  published by default.
- The **publishable** form (`HammerReceipt.to_publishable_dict()` /
  `build_publishable_view`) redacts every one of those fields to a
  `<redacted:label length=N digest=...>` placeholder (length and content
  digest only — never the raw text), then scans every remaining string
  leaf for credential-shaped content (API keys, bearer/JWT tokens,
  private-key blocks) and scrubs it, and fully replaces the value of any
  dict key that looks like a credential field name. Only this redacted
  view — never the full receipt — should be shared outside the operator's
  own trust boundary. Release evidence (`data/logic/itp_hammer/
  release-evidence.json`) references receipt ids and status/kernel-
  acceptance metadata only; it does not embed private goal or solver
  text.
- No user prompt, credential, or private theorem source is ever
  transmitted to an external solver process's command line — only a
  resolved executable path and a file path pointing at already-serialized,
  translated input (see `docs/logic/itp_hammer_security_model.md` §4).
- An LLM-assisted premise ranking or subgoal decomposition (opt-in,
  disabled by default) is redacted and requires explicit human review
  before use; it can never itself constitute a verified proof or suppress
  an `unsupported_translation` result (HAMMER-011).

## 9. Limitations

- **No higher-order, dependent-type, or unresolved-polymorphic
  translation.** These fail closed with `unsupported_translation`; they
  are never approximated.
- **A solver verdict is never trusted on its own.** `candidate`,
  `counterexample`, `timeout`, and `unknown` are all explicitly
  *unverified* outcomes even when a solver reports `proved`/`unsat`.
- **Only Lean 4, Coq/Rocq, and Isabelle/HOL have native reconstruction
  support.** A goal from any other ITP or a plain-text theorem statement
  cannot be verified by this pipeline — it can, at most, produce an
  unverified candidate via translation to TPTP/SMT-LIB (if the fragment is
  supported) with no possibility of ever reaching `VERIFIED`.
- **The import-overlap "relevant premise" proxy is not a mathematical
  ground truth** — it approximates topical relatedness from declared
  imports, not actual logical necessity. Recall/latency numbers from §4
  should be read as a regression signal against this pipeline's own prior
  runs, not as an absolute measure of premise-selection quality against
  an external benchmark like the Mizar Mathematical Library or
  Archive of Formal Proofs.
- **The learned/graph-based premise selector (HAMMER-005) is
  experimental and opt-in.** It is gated behind a pinned model digest and
  falls back to the deterministic baseline whenever the model is missing,
  unreadable, or its digest does not match; it must never be treated as
  more authoritative than the baseline without a held-out comparison (see
  `benchmarks/bench_itp_hammer_premise_selection.py`).
- **Native automation and decomposition fallbacks are bounded.** The
  HAMMER-011 recovery pipeline only ever tries a small, explicitly
  enabled set of native closing tactics and a bounded subgoal
  decomposition (`HammerPolicy.max_decomposition_subgoals`); it is not a
  general-purpose automated theorem prover.
- **Fixture-scale benchmarking.** `tests/fixtures/logic/hammers/
  golden_corpus.json` is a small (six-theorem), hand-built,
  Mathlib-naming-convention-following fixture — not a real excerpt of
  Mathlib4 — used specifically so `benchmarks/bench_itp_hammer.py` and
  the release gate's golden-case receipts are fast, deterministic, and
  license-clean to run in CI. It is not a substitute for benchmarking
  against a real large-scale theorem corpus before drawing conclusions
  about premise-selection quality at production scale.
