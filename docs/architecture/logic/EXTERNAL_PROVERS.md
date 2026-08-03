# External provers, hammers, backends, and lazy provisioning

| Field | Value |
| --- | --- |
| Interface | `ExternalProverArchitecture@1` |
| Task | `IPFSDOC-042` |
| Status | `canonical` |
| Owner | architecture / logic-proof |
| Source of truth | `ipfs_datasets_py/logic/external_provers/`; `ipfs_datasets_py/logic/hammers/`; `ipfs_datasets_py/logic/backends/`; `ipfs_datasets_py/logic/bridge/external_prover_router.py`; `ipfs_datasets_py/logic/ir_core/protocols.py`; `ipfs_datasets_py/logic/common/feature_detection.py`; `scripts/setup/ipfs_prover_installer.py`; [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md); [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, operator |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow D, [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md), `docs/logic/itp_hammer_contract.md`, `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` |
| Review cadence | when prover adapters, hammer trust contracts, lazy-install policy, or result-authority bindings change |

## 1. Purpose

This guide answers: **how external SAT/SMT solvers and interactive theorem
provers (ITPs) attach to the logic stack, how the ITP hammer pipeline selects
premises and runs a portfolio without becoming trusted proof, how adapters and
native/system dependencies are discovered and provisioned, and how
timeouts, cancellation, caches, and receipts form a typed lifecycle with
non-interchangeable outcomes.**

It is the companion leaf to
[IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) (kernel identity and
authority kinds) and
[COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md)
(formalization and reconstruction without proof). This document owns
**backend routing**, **hammer premise/portfolio/reconstruction**, **lazy
user-local installation**, **capability probing**, and the **typed
proved / countermodel / UNKNOWN / unsupported / unavailable** outcome
taxonomy for external solver work.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → accepted ADRs → maintained guides → historical
material ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place new prover work without inventing a second trust kernel or collapsing SAT into theorem authority |
| **Adapter author** | Implement bridges that probe capability, fail closed when missing, and never promote solver stdout to `VERIFIED` |
| **Hammer / portfolio operator** | Configure timeouts, allowlists, cancel-on-first-conclusive, and receipt retention |
| **Security / policy reviewer** | Separate trusted-kernel checks from untrusted SAT/SMT/runtime/evidence signals |
| **Installer / SRE** | Understand lazy user-local paths, env gates, and that binary presence ≠ production capability |

## 3. Scope and non-goals

### In scope

- **Authority separation**: trusted ITP kernel vs SAT/SMT vs runtime monitor
  vs evidence readiness vs policy approval.
- **External prover adapters**: Z3, CVC5, Lean, Coq, Vampire, E, and related
  bridges under `logic.external_provers` and `logic.backends`.
- **ITP hammer pipeline**: premise selection, translation to TPTP/SMT-LIB,
  portfolio execution, provenance normalization, reconstruction, receipts.
- **Capability probing** without import-time side effects.
- **Lazy user-local installation** of native solvers and optional Python
  bindings.
- **Lifecycle**: timeout, cancel, process-group ownership, cache keys,
  content-addressed receipts.
- **Typed outcomes**: proved / verified, countermodel / counterexample,
  UNKNOWN, unsupported, unavailable (plus timeout, error, policy-denied).

### Non-goals

- Kernel canonicalization and IR family ownership (owned by
  [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md)).
- Compiler/decompiler semantic round-trip metrics (owned by
  [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md)).
- Governed authorization composition and ZKP attestation profiles (later
  logic leaves under IPFSDOC-043 / result-authority docs).
- Full OS packaging recipes for every distribution (installer is best-effort;
  operators may install system packages manually).
- Treating neural/LLM prover confidence, monitor green status, or cache hits
  as theorem authority.

## 4. Mental model

```text
  formalized goal / ITP obligation
           │
           ▼
  ┌────────────────────────────────────────────────────────┐
  │  adapters + capability probe + optional lazy install   │
  └───────────────────────────┬────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   SMT bridges           ATP portfolio        ITP frontends
   (Z3, CVC5, …)        (Vampire, E, …)      (Lean, Coq, Isabelle)
          │                   │                   │
          └─────────┬─────────┘                   │
                    ▼                             │
         untrusted solver attempt                 │
         sat / unsat / proved / UNKNOWN           │
         + evidence (stdout digest, model, core)  │
                    │                             │
                    ▼                             │
         proof candidate (never VERIFIED)         │
                    │                             │
                    └──────────► reconstruction ◄─┘
                                 (native tactic/script)
                                        │
                                        ▼
                              ITP kernel check
                         (only path to VERIFIED /
                          theorem_proof authority)
                                        │
                                        ▼
                              receipt + cache + audit
```

**Solver success is a candidate. Kernel acceptance is proof authority.**
Everything else (timeout, missing binary, unsupported construct, policy
deny) is an explicit non-proof outcome—not a silent failure and not a
promoted success.

## 5. Trusted-kernel versus SAT / SMT / runtime / evidence authority

### 5.1 Layered, non-interchangeable kinds

`logic.ir_core.protocols.AuthorityKind` is a **closed, non-hierarchical**
enumeration. A result carries exactly one kind; renaming fields or sharing a
generic `ok` boolean across kinds is forbidden on trust-bearing paths
([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

| Authority kind | What it establishes | Typical producers | Does **not** establish |
| --- | --- | --- | --- |
| `theorem_proof` | A formal property was checked under a declared kernel or attested proof path | ITP kernel reconstruction (`hammers.reconstruction`); attested proof corpus under theorem authority | Authorization to act; completeness of the real world |
| `satisfiability` | A SAT/SMT/ATP solver reported sat / unsat (or equivalent) for a modeled query under explicit assumptions | Z3, CVC5, Vampire, E portfolio attempts | Theorem proof under a different theory/kernel; policy allow |
| `runtime_monitor` | A monitor observed satisfied / violated / unknown for a runtime property | Observability / monitor adapters | Proof of safety; authorization |
| `evidence_readiness` | Required evidence artifacts are ready or not ready | Evidence gates, corpus membership checks | Proof or policy grant |
| `policy_approval` | Policy evaluation approved / rejected / unknown | Admissibility / authorization compose | Theorem authority |

Aliases in code (`PROOF`, `EVIDENCE_GATE`, `POLICY_DECISION`, …) resolve to
the same closed set; they are not additional authority layers.

### 5.2 Trusted kernel

In the hammer pipeline, **trusted kernel** means the target ITP's own
elaborator/checker (Lean, Coq, Isabelle) running under a pinned
`EnvironmentLockRecord`. Only a `ReconstructionRecord` with
`kernel_accepted=True` may promote a run to `HammerResultStatus.VERIFIED`
(`logic.hammers.models`). That invariant is enforced at construction and
validation time; setting `status=verified` without a kernel-accepted
reconstruction is rejected.

Direct SMT bridges (Z3/CVC5) that report “proved” for a validity query are
reporting **solver-local** unsatisfiability of the negated goal. That is
`satisfiability` (or a solver-scoped proof claim), **not** interchangeable
with ITP-kernel `theorem_proof` unless a separately declared attestation path
binds them.

### 5.3 SAT and SMT

| Mode | Question | Common tools | Raw verdicts |
| --- | --- | --- | --- |
| **SAT** (propositional / bit-blasted fragments) | Is the formula satisfiable? | Z3, CVC5 (propositional cores) | `sat`, `unsat`, `unknown`, `timeout` |
| **SMT** (theories: arithmetic, arrays, strings, …) | Satisfiable modulo theories? | Z3, CVC5 | same + models / unsat cores |
| **ATP** (first-order automated provers) | Prove / refute under TPTP encoding? | Vampire, E | `proved`, `disproved`, `unknown`, `timeout` |

`SolverVerdict` in the hammer contract treats all of these as **untrusted**
raw claims. Portfolio code never exposes them as `VERIFIED`.

### 5.4 Runtime and evidence

- **Runtime monitor** outcomes (`monitor_satisfied` / `monitor_violated`)
  describe observed execution behavior. They must not be relabeled as
  `proved` theorems or as policy allows.
- **Evidence readiness** (`ready` / `not_ready`) describes whether
  artifacts, signatures, or corpus rows required by a gate are present. SAT
  alone, cache presence alone, or “no deny retrieved” does not satisfy proof
  or authorization composition (see Flow D invariants in
  [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md)).

### 5.5 Substitution rules (fail-closed)

| Forbidden promotion | Correct handling |
| --- | --- |
| SAT `unsat` → theorem `proved` | Keep `satisfiability` + `unsatisfiable`; optional hammer reconstruction may later yield kernel `VERIFIED` |
| Solver `proved` → authorization `allow` | Policy/authorization layers re-evaluate under their own profiles |
| Monitor green → proof | Remain `runtime_monitor` |
| Cache hit → capability | Cache returns a stored typed result; it does not install missing solvers |
| Binary on `PATH` → production-ready | Capability probe + version/smoke checks; install docs separate |
| Neural confidence ≥ threshold → kernel proof | Neural bridges remain heuristic / evidence unless independently kernel-checked |

## 6. Package map

| Package / path | Role |
| --- | --- |
| `logic.external_provers` | Lazy bridges for Z3, CVC5, Lean, Coq, SymbolicAI; `ProverRouter`; formula analysis; proof cache; monitoring |
| `logic.external_provers.lazy_installer` | Opt-in best-effort install; user-local root; progress events |
| `logic.external_provers.smt` | Z3 / CVC5 bridge implementations |
| `logic.external_provers.interactive` | Lean / Coq bridge implementations |
| `logic.external_provers.neural` | SymbolicAI / LLM-assisted guidance (non-kernel) |
| `logic.backends` | Solver adapters implementing kernel backend protocols (`backends.z3`, `backends.cvc5`) |
| `logic.bridge.external_prover_router` | Bridge-layer routing surface for multi-view formalization |
| `logic.hammers` | ITP hammer: corpus, premise selection, translation, portfolio, provenance, reconstruction, receipts |
| `logic.hammers.process_lifecycle` | Process-group ownership, timeout, cancel, durable manifests |
| `logic.common.feature_detection` | Quiet importability probes without loading heavy deps |
| `scripts/setup/ipfs_prover_installer.py` | CLI installer (`ipfs-datasets-install-provers`) for native tools |
| `logic.integration.reasoning.*hammer*` | Legal-IR / Leanstral hammer integration and backends |

Optional packaging:

| Extra / entry | What it provides |
| --- | --- |
| pip extra `theorem-provers` (hyphen) | Python bindings and related helpers (`z3-solver`, `cvc5`, …) where packaged |
| Native Lean / Coq / Vampire / E / ErgoAI | **Not** fully shipped in-wheel; user-local or OS packages via lazy installer or manual install |
| Env auto-install flags | `IPFS_DATASETS_PY_AUTO_INSTALL_Z3`, `IPFS_DATASETS_PY_AUTO_INSTALL_CVC5`, … (see installer) |

## 7. Adapters and native / system dependencies

### 7.1 Adapter contract

An **adapter** (bridge) maps a formal goal plus axioms into a tool-specific
encoding, invokes the tool under budgets, and normalizes the outcome into a
typed result. Adapters must:

1. **Import cleanly** when the backend is missing (optional import; flags such
   as `Z3_AVAILABLE`, `CVC5_AVAILABLE`, `LEAN_AVAILABLE`, `COQ_AVAILABLE`).
2. **Probe before claim** — discovery of a module or binary is not success.
3. **Invoke with literal argv** (`shell=False`); never interpolate user
   formula text into a shell string (hammer portfolio invariant).
4. **Bound** wall time, memory, and process count when the process supervisor
   is in use.
5. **Emit typed outcomes** (proved / countermodel / UNKNOWN / unsupported /
   unavailable / timeout / error)—never a bare boolean for trust paths.
6. **Prefer cache-by-content** when enabled, without changing authority kind.

### 7.2 Dependency classes

| Class | Examples | Provisioning |
| --- | --- | --- |
| **Python package bindings** | `z3` (`z3-solver`), `cvc5`, `pysmt` | pip / optional extra `theorem-provers` |
| **Native CLI solvers** | `cvc5`, `vampire`, `eprover` | OS package, release binary, or lazy install into user-local root |
| **ITP toolchains** | Lean 4 (`elan`/`lake`), Coq (`coqc` / opam), Isabelle | User toolchain managers; not required for package import |
| **Security / domain tools** | Apalache, Tamarin, Maude, ProVerif | Optional; same lazy-install alias table |
| **Neural / API** | SymbolicAI + LLM credentials | pip + env keys; stochastic; non-kernel |
| **F-logic / ErgoAI** | ErgoEngine / `runErgo.sh` | Optional; git or release URL overrides |

### 7.3 Path resolution order

`lazy_installer.find_executable` prefers:

1. Explicit env override `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE`
2. Managed user-local roots (`~/.local/bin`, elan/opam bins,
   `$IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT/bin`, default
   `~/.local/share/ipfs_datasets_py/theorem-provers/bin`)
3. System `PATH`

This keeps CI hermetic when overrides point at fixtures, and keeps developer
machines able to use user-local installs without root.

## 8. Capability probing

### 8.1 Quiet module probes

`logic.common.feature_detection` uses `importlib.util.find_spec` so optional
dependencies can be tested **without importing** them and without import-time
warnings. Warnings are gated by `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS`.
Hermetic/minimal modes (`IPFS_DATASETS_PY_MINIMAL_IMPORTS` /
`IPFS_DATASETS_PY_BENCHMARK`) force “unavailable” so benchmarks do not
accidentally pull heavy stacks.

### 8.2 Runtime capability matrix

Capability is multi-dimensional:

| Probe | Pass means | Fail maps to |
| --- | --- | --- |
| Module importable | Python binding present | `unavailable` (Python dep) |
| Executable on managed path | Binary found | `unavailable` (native tool) |
| Version / smoke query | Tool answers a fixed trivial query | `unavailable` or `error` |
| Theory / fragment support | Encoding is representable | `unsupported` / `unsupported_translation` |
| Policy allowlist | Solver name permitted | `policy_denied` |
| Resource budget remaining | Lease acquired | cancel / timeout / unknown |

**Discovery of a prover binary ≠ capability** until install and smoke tests
say so ([END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) §7.3).

### 8.3 Public helpers

| Helper | Location | Behavior |
| --- | --- | --- |
| `get_available_provers()` | `external_provers` | List currently importable bridges |
| `check_prover_availability(name)` | `external_provers` | Boolean for a named prover |
| Frontend capability evidence | `hammers.frontends` | Structured “unavailable frontend” evidence for Lean/Coq/Isabelle |
| Formula analyzer | `external_provers.formula_analyzer` | Complexity/type hints for router strategy |

Hammer frontends capture structured capability evidence when an ITP is not
installed so callers can distinguish **unsupported goal** from **missing
tool**.

## 9. Lazy user-local installation

### 9.1 Design principles

1. **Import is free** — bridges and routers load without installing anything.
2. **Install is opt-in** — global or per-prover environment gates.
3. **User-local preferred** — default root under the user's home share tree;
   root/apt only when explicitly allowed and appropriate.
4. **Visible progress** — `ProverInstallEvent` phases (`checking`,
   `installing`, `installed`, `failed`, `disabled`, `blocked`, `available`)
   so first-use downloads are not silent.
5. **At-most-once attempt per process** — locks and attempt sets avoid install
   storms.
6. **Fail closed for trust** — failed install yields `unavailable`, not a
   simulated proof.

### 9.2 Environment controls

| Variable | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1` | Enable requested-prover installs |
| `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>=0/1` | Per-prover override (e.g. `Z3`, `CVC5`, `LEAN`) |
| `IPFS_DATASETS_PY_LAZY_INSTALL_STRICT=1` | Raise on installer failure instead of soft unavailable |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1` | Permit interactive sudo paths (e.g. Coq) |
| `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` | User-local native artifact root |
| `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE` | Pin executable / portable runtime launcher |
| `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND` | Override install command when no packaged release |
| `IPFS_DATASETS_PY_AUTO_INSTALL_Z3` / `_CVC5` / … | Setup-time auto-install hooks |
| `IPFS_DATASETS_PY_ERGOAI_*` | ErgoAI git/release URL and install dir overrides |

### 9.3 Operator entry points

```bash
# Unified native installer (console script)
ipfs-datasets-install-provers --z3 --cvc5
# or
python scripts/setup/ipfs_prover_installer.py --z3 --cvc5 --lean

# Python bindings only (no native Lean/Coq)
pip install 'ipfs-datasets-py[theorem-provers]'
```

API surface (when import succeeds):

- `lazy_installs_enabled()`, `prover_lazy_install_enabled(name)`
- `lazy_install_prover(name, progress=...)`
- `ensure_prover_executable(name)` — probe then optional install

### 9.4 What lazy install is not

- Not a substitute for CI pinning of solver versions in production attestation
  environments.
- Not automatic network access in hermetic/minimal import modes.
- Not permission to treat a freshly downloaded binary as kernel-trusted without
  environment lock and reconstruction (for hammers) or declared attestation.

## 10. Hammer pipeline: premise selection, portfolio, reconstruction

The ITP hammer (`logic.hammers`) is the production trust contract for
“Sledgehammer-style” automation: select premises, lower to ATP/SMT formats,
run a portfolio, normalize evidence, reconstruct into the originating ITP,
and only then claim verification. Narrative specs live under
`docs/logic/itp_hammer_*.md`; this section is the architecture summary.

### 10.1 End-to-end stages

| Stage | Module | Output record | Authority |
| --- | --- | --- | --- |
| Request | `models.HammerRequest` | Versioned goal + policy | none yet |
| Corpus | `corpus` | Content-addressed theorems + `corpus_revision` | evidence of premise identity |
| Premise selection | `premise_selection`, optional `learned_selector` | Bounded `top_k` premises + exclusion reasons | ranking only |
| Frontend snapshot | `frontends` | Native goal, hyps, imports, ITP version | ITP context capture |
| Translation | `translation`, `tptp`, `smtlib` | TPTP / SMT-LIB + obligations | may be `unsupported` |
| Portfolio | `portfolio` + `policy` | Parallel solver attempts | **untrusted** `SolverVerdict` |
| Provenance | `provenance` | Normalized proof steps / unsat core / model | recommends candidate / counterexample / UNKNOWN only |
| Reconstruction | `reconstruction` + `reconstructors` | Native script + kernel check | **only** path to `VERIFIED` |
| Fallbacks | `fallbacks` | Native automation or decomposition plan | still needs independent kernel check |
| Receipt | `receipts` | Content-addressed `HammerReceipt` | audit / replay |

### 10.2 Premise selection

**Deterministic baseline** (`premise_selection`):

- Extracts goal symbol / type / import features and a one-hop dependency-graph
  proximity signal.
- Produces a stable, bounded `top_k` ranking.
- Records an **explicit exclusion reason** for every non-selected candidate
  (auditability; no silent drops).

**Optional learned selector** (`learned_selector`):

- Opt-in only; pinned content-addressed `LearnedModelArtifact`.
- Gated entry point always falls back to the deterministic baseline when the
  model is missing, mismatched, policy-denied, or not enabled.
- Learned ranking never sets kernel authority bits.

### 10.3 Translation

Goals and premises lower to **TPTP** and/or **SMT-LIB** with explicit
monomorphization, lambda elimination/lifting, and type encodings. Unsupported
dependent / higher-order / polymorphic constructs must yield
`TranslationStatus.UNSUPPORTED` (or `PARTIAL`) with obligations—**never**
silent drop to “make the translation succeed.”

If no supported translation exists, the hammer finishes as
`unsupported_translation` **before** any solver runs.

### 10.4 Portfolio execution

`SolverPortfolio` runs an **allowlisted** set such as **Z3**, **CVC5**,
**Vampire**, and **E** under `PortfolioPolicy`:

- Per-solver wall time, CPU, and memory budgets.
- Global max parallel processes and host resource leases.
- `cancel_on_first_conclusive` (default): when one attempt returns a
  conclusive `sat` / `unsat` / `proved` / `disproved`, sibling process groups
  are cancelled; cancelled attempts are recorded as `unknown`, not fabricated
  as conclusive.
- Every attempt captures exact argv, input digest, stdout/stderr digests,
  exit status, timeout flag, and a short trace excerpt
  (`SolverAttemptEvidence`).
- Content reaches solvers only via temporary files; argv never embeds user
  theorem text in a shell string.

### 10.5 Provenance normalization

Raw solver output becomes `NormalizedEvidence` with kinds such as proof,
unsat core, model / counterexample, absent, malformed, or unsupported.
Recommended hammer statuses from this stage are only **`candidate`**,
**`counterexample`**, or **`unknown`**—never **`verified`**.

### 10.6 Reconstruction (trusted step)

Reconstructors do not claim a general sound TSTP→native proof translator.
They:

1. Use solver-suggested premise ids only as **hints** against real local
   hypotheses in the captured `GoalSnapshot`.
2. Try a fixed, deterministic set of native closing tactics.
3. Ask the **real ITP kernel** once under an `EnvironmentLockRecord`.

`kernel_accepted=True` is derived from subprocess exit status and output,
never assumed. Corrupted traces or wrong theorem statements fail closed
(non-`VERIFIED`).

### 10.7 Fallbacks

On translation, search, or reconstruction failure:

1. Optional operator-enabled **native automation** (empty-premise candidate;
   no untrusted solver).
2. Else a bounded **decomposition plan** (structural and/or policy-gated,
   redacted, human-reviewed LLM-suggested subgoals).

Each subgoal still requires its own independent native kernel check before
any verified claim.

## 11. Timeout, cancel, cache, and receipt lifecycle

### 11.1 Process lifecycle

`hammers.process_lifecycle` owns theorem-prover **subprocesses and their
children** (lake, plugins, ATP workers):

- New process group per managed command.
- Durable ownership manifest with PID birth markers and env tokens (no
  “kill by executable name”).
- Heartbeats while alive; TERM then KILL; registry removal only after the
  whole group exits.
- Wall-clock and OS resource limits (`ProcessLimits`).
- Cancellation signals and leases integrate with portfolio cancel-on-first
  and global resource schedulers.

A plain `subprocess.run(..., timeout=...)` is **not** sufficient when
solvers spawn grandchildren.

### 11.2 Timeout semantics

| Layer | Behavior | Typed outcome |
| --- | --- | --- |
| Per-solver budget | Attempt stops; record `SolverVerdict.TIMEOUT` | attempt timeout |
| Portfolio total | No conclusive attempt | `HammerResultStatus.TIMEOUT` or `UNKNOWN` |
| Bridge default (e.g. Z3 5s, Lean 30s) | Bridge returns not-proved with reason | timeout / UNKNOWN, not false `proved` |
| Install / download | Separate from proof budgets | install `failed` / `blocked` |

Timeout is **never** rewritten as `disproved` or `unsatisfiable`.

### 11.3 Cancel semantics

- Cooperative cancellation via shared signals / leases.
- Portfolio cancel marks siblings `unknown` with cancel reason in evidence.
- Attempt status vocabulary at the protocol layer includes `cancelled`
  (`AttemptStatus.CANCELLED` in `ir_core.protocols`).
- Cancelled work must not leave orphan process groups.

### 11.4 Cache lifecycle

| Cache | Key material | Stores | Invalidation notes |
| --- | --- | --- | --- |
| External prover proof cache | Formula + axioms + prover id + config (CID / digest) | Normalized proof results | Config or prover version change → miss |
| Hammer proof cache | Request digests / corpus revision | Replayable partials | Corpus revision mismatch rejected |
| Legal-IR / Leanstral artifact caches | Obligation digests | Compact verification summaries | Policy pins |
| Feature-detection LRU | Module names | Importability booleans | `clear_feature_detection_cache()` after install |

Cache hits **replay a prior typed result**. They do not upgrade authority or
install missing tools. Simulation / stub results must remain labeled if
present in a corpus.

### 11.5 Receipt lifecycle

A `HammerReceipt` bundles:

- Canonical `HammerResult` (request, premises, translations, attempts,
  candidate, reconstruction, environment lock, status).
- Out-of-band evidence (solver stdout/stderr, normalized evidence,
  reconstruction kernel I/O, optional decomposition plan).

Properties:

- `receipt_id` is a **content digest**, not a mutable label.
- `ReceiptStore` always writes local disk; optional IPFS push with local
  fallback on failure.
- **Publishable view** redacts private theorem sources, raw prompts, and
  credential-shaped strings; publishable views are not full replay bundles.

Receipts are **audit and replay** artifacts (ADR-003 layer “receipts”). They
do not by themselves promote weak evidence to strong authority.

### 11.6 Lifecycle diagram

```text
  request admitted
       │
       ├─ policy deny ──────────────────────────► POLICY_DENIED
       ├─ missing capability ───────────────────► UNAVAILABLE
       ├─ translation unsupported ──────────────► UNSUPPORTED_TRANSLATION
       │
       ▼
  portfolio run (leases + process groups)
       │
       ├─ all timeout ──────────────────────────► TIMEOUT
       ├─ cancel / no conclusive ───────────────► UNKNOWN
       ├─ sat / model ──────────────────────────► COUNTEREXAMPLE (untrusted)
       └─ unsat / proved certificate ───────────► CANDIDATE (untrusted)
                │
                ▼
         reconstruction + kernel
                │
                ├─ kernel_accepted ─────────────► VERIFIED  (theorem path)
                └─ rejected / fail ─────────────► CANDIDATE / fallback plan
                │
                ▼
         persist receipt + optional cache write
```

## 12. Typed outcomes

Outcomes must remain **explicit**. Callers map them into domain envelopes
without collapsing categories.

### 12.1 Kernel / theorem path (`HammerResultStatus`)

| Status | Meaning | Typical cause |
| --- | --- | --- |
| `verified` | Kernel accepted reconstructed proof | Only with `kernel_accepted` reconstruction |
| `candidate` | Untrusted solver certificate not yet (or not) kernel-checked | Portfolio success without reconstruction |
| `counterexample` | Untrusted countermodel / refutation | SAT model / disproved |
| `unknown` | No conclusive solver verdict within policy | Open search, cancel, inconclusive |
| `timeout` | All attempted solvers exhausted budgets | Wall-clock limits |
| `unsupported_translation` | Cannot lower constructs honestly | HOL / dependent features |
| `unavailable` | Required ITP/solver/frontend missing | Not installed; capability fail |
| `policy_denied` | Allowlist/budget/network policy forbade run | Before execution |

### 12.2 Raw solver verdicts (`SolverVerdict`)

`sat`, `unsat`, `proved`, `disproved`, `unknown`, `timeout`, `error` —
**never** equivalent to `HammerResultStatus.VERIFIED`.

### 12.3 Protocol-level result statuses (`ResultStatus` × `AuthorityKind`)

| Authority | Allowed statuses (subset) |
| --- | --- |
| `theorem_proof` | `proved`, `disproved`, `unknown`, `error` |
| `satisfiability` | `satisfiable`, `unsatisfiable`, `unknown`, `error` |
| `runtime_monitor` | `monitor_satisfied`, `monitor_violated`, `unknown`, `error` |
| `evidence_readiness` | `ready`, `not_ready`, `unknown`, `error` |
| `policy_approval` | `approved`, `rejected`, `unknown`, `error` |

Attempt terminals additionally include `timed_out`, `unavailable`,
`cancelled` (`AttemptStatus`).

### 12.4 Acceptance-facing taxonomy (documentation contract)

For product and agent documentation, use this five-way language and map
inward to the enums above:

| Outcome word | Means | Maps from (examples) |
| --- | --- | --- |
| **proved** / **verified** | Trusted check accepted the goal | `VERIFIED`; `ResultStatus.PROVED` under `theorem_proof` |
| **countermodel** / **counterexample** | Model or refutation of the claim | `COUNTEREXAMPLE`; `SATISFIABLE` when validity was expected; `DISPROVED` |
| **UNKNOWN** | Inconclusive within budget/policy | `UNKNOWN`, cancelled siblings, open search |
| **unsupported** | Encoding/theory/fragment cannot represent the goal honestly | `UNSUPPORTED_TRANSLATION`, `TranslationStatus.UNSUPPORTED` |
| **unavailable** | Tooling or capability not present | missing Z3/CVC5/Lean binary or binding; install disabled/failed |

Always retain **timeout**, **error**, and **policy_denied** as first-class
adjacent outcomes; do not fold them into **proved**.

### 12.5 Simulation and stubs

Simulation, artifact-membership, and stub backends **never** upgrade to
production theorem authority (`proof_corpus` policy; Flow D). Documents and
APIs must label them explicitly when exposed.

## 13. Routing strategies

`ProverRouter` (and related bridge routers) coordinate multiple adapters:

| Strategy | Behavior |
| --- | --- |
| Auto | Formula analyzer picks a preferred backend |
| Parallel | Race allowed provers under a shared timeout |
| Sequential | Ordered fallback until success or exhaustion |
| Fastest | Prefer low-latency SMT (typically Z3) |
| Most capable | Prefer ITP / heavy solvers when available |

Routing selects **who runs**. It does not change authority kinds. Parallel
wins still need kernel reconstruction for hammer `VERIFIED`.

Deterministic route selection for fixed pipelines uses
`select_deterministic_prover_route` /
`DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION` for replayable strategy pins.

## 14. Security and operational invariants

1. **No shell interpolation** of theorem or premise text into commands.
2. **No hierarchy of authority kinds** — exact match only
   (`ResultAuthority.permits` / `require`).
3. **Solver stdout is evidence**, not kernel acceptance.
4. **Cancel and timeout leave audit trails** (attempt records), not silent
   omission.
5. **Lazy install is gated** and emits progress; hermetic modes refuse side
   effects.
6. **Publishable receipts redact** secrets and private sources.
7. **Proof ≠ authorization ≠ dispatch** (ADR-003 stack).
8. **Fail closed** on missing capability, unsupported translation, and policy
   deny ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

## 15. Operator checklist

| Goal | Action |
| --- | --- |
| Import package without solvers | Default install; probes report empty availability |
| Enable Z3 Python path | `pip install z3-solver` or `[theorem-provers]` |
| Enable CVC5 | `pip install cvc5` and/or native `cvc5` CLI |
| Enable Lean hammer reconstruction | Install Lean 4 toolchain; ensure `lean`/`lake` on managed path |
| User-local native tools | `ipfs-datasets-install-provers --z3 --cvc5` with lazy env flags as needed |
| Pin executables in CI | Set `IPFS_DATASETS_PY_*_EXECUTABLE` and disable lazy install |
| Debug portfolio | Inspect `SolverAttemptRecord` + evidence digests; do not trust raw “proved” strings alone |
| Share results externally | Use `HammerReceipt.to_publishable_dict` / redacted view |
| Hermetic benchmarks | `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` or benchmark flag |

## 16. Discrepancies and deferred items

| Item | Status |
| --- | --- |
| Full general TSTP/SMT proof → native proof-term reconstruction | Deferred / research; current reconstructors use premise hints + native closing tactics |
| All native provers shipped in-wheel | Not planned; lazy/user-local or OS packages |
| Neural SymbolicAI as theorem_proof authority | Not accepted without independent kernel/attestation path |
| Unified single enum across TDFOL `ProofStatus`, hammer statuses, and `ResultStatus` | Multiple typed surfaces today; map at boundaries rather than collapsing |
| Auto-install requiring root on minimal containers | Best-effort; may remain `unavailable` without operator action |
| Cross-view “equivalent” auto-proved by solvers | Not implied by semantic round-trip; needs explicit proof portfolio |

## 17. Related documents

| Document | Relationship |
| --- | --- |
| [IR_FAMILY_AND_IDENTITY.md](./IR_FAMILY_AND_IDENTITY.md) | Kernel identity, provenance, authority kinds (IPFSDOC-040) |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](./COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Formalization without proof (IPFSDOC-041) |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Non-interchangeable authority stack |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Fail-closed degradation |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow D prove/check and hammer hops |
| `docs/logic/itp_hammer_contract.md` | Full hammer trust contract narrative |
| `docs/logic/itp_hammer_premise_selection.md` | Premise selection detail |
| `docs/logic/itp_hammer_receipts.md` | Receipt store and redaction |
| `docs/logic/itp_hammer_security_model.md` | Hammer security model |
| `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | User-oriented integration walkthrough |
| `ipfs_datasets_py/logic/external_provers/README.md` | Package-local adapter notes |

## 18. Summary invariants

1. **Trusted kernel acceptance is the only hammer path to `VERIFIED`**;
   SAT/SMT/ATP verdicts are untrusted candidates or countermodels.
2. **Authority kinds are non-hierarchical and non-substitutable**;
   satisfiability, runtime monitoring, evidence readiness, and policy
   approval never silently become theorem proof.
3. **Premise selection is bounded and auditable**; learned ranking is opt-in
   and falls back to the deterministic baseline.
4. **Portfolio runs are allowlisted, resource-bounded, cancellable, and
   fully recorded**; cancel does not invent conclusive verdicts.
5. **Adapters separate Python bindings from native/system tools**; capability
   probing is quiet and hermetic-mode aware.
6. **Lazy installation is user-local and opt-in**; failure yields
   `unavailable`, not simulated success.
7. **Timeout, cancel, cache, and receipt** form an explicit lifecycle;
   receipts audit and replay but do not upgrade weak evidence.
8. **Typed outcomes**—proved/verified, countermodel, UNKNOWN, unsupported,
   unavailable—must remain distinct in APIs, docs, and agent reasoning.
