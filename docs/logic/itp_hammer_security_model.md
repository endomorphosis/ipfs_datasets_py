# ITP Hammer Security Model

Status: Implemented (HAMMER-015)
Date: 2026-07-19
Modules: `ipfs_datasets_py.logic.hammers.*`
Release gate: `scripts/ops/logic/release_itp_hammer_gate.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md`
(HAMMER-001, the trust contract this document explains the security
rationale for), `docs/logic/itp_hammer_capability_inventory.md`
(HAMMER-002), `docs/logic/itp_hammer_failure_policy.md` (HAMMER-011),
`docs/logic/itp_hammer_receipts.md` (HAMMER-012),
`docs/logic/itp_hammer_mcp_contract.md` (HAMMER-013), and
`docs/logic/itp_hammer_user_guide.md` (this task's companion document,
HAMMER-015).

## 1. Threat model

The ITP hammer pipeline executes external, potentially attacker-influenced
processes (solvers, ITP kernels) against content that may itself be
attacker-influenced (goal statements, corpus premises, solver output) and
is designed to be reachable from three surfaces: direct Python import, a
local CLI, and an MCP server that may be driven by an LLM agent. The
security model below defends against the following threat classes, each
with a link to the mechanism that mitigates it:

| Threat | Mitigation | Where |
|---|---|---|
| An untrusted solver lies about proving a theorem | Solver output can only ever produce a `candidate`/`counterexample`, never `verified`, until an independent kernel check accepts a reconstructed native proof | §5, `models.HammerResult.__post_init__` |
| A malicious/malformed proof trace is fed back to a kernel | Reconstruction validates the candidate/premise/translation-map coherence before ever invoking a kernel; a malformed trace yields `candidate`/`unknown`, never `verified` | `reconstruction.py`, HAMMER-009/010 |
| Command injection via a crafted goal/premise/theorem id | No user/corpus content is ever interpolated into a shell string; every subprocess call passes an argv list with a resolved executable path and a file path, never `shell=True` | §4 |
| Unbounded resource consumption (CPU/memory/wall-clock/process count) from a crafted or adversarial input | Every external process is bounded by an explicit, operator-controlled `HammerPolicy`/`PortfolioPolicy`/`SolverBudget` (timeout, `RLIMIT_CPU`, `RLIMIT_AS`, max parallel processes) | §2 |
| Data exfiltration via network access from a solver/kernel subprocess | `HammerPolicy.network_allowed` defaults to `False`; enabling it is an explicit, auditable operator decision | §2 |
| An LLM agent silently accepting/fabricating a proof or suppressing an unsupported-translation result | LLM-assisted premise ranking/decomposition is opt-in, redacted, requires human review, and can never itself promote a result to `verified` or bypass an `unsupported_translation` outcome | §7, HAMMER-011 |
| A caller launching a real native process (Lean/Coq/Isabelle/solver) without realizing it | Every operation that launches a real process (`inspect`, `run-candidate`, `reconstruct`) requires an explicit `confirm_native_execution=True` (CLI: `--confirm`) | §3 |
| Leakage of a private theorem, translated formula, or raw kernel/solver output through a shared receipt | The publishable receipt view redacts every one of those fields to a length+digest placeholder and scrubs credential-shaped strings | §8 |
| A stale, drifted, or fabricated release claim ("this pipeline verifies theorems") | The release gate independently reloads and re-validates every referenced receipt, cross-checks corpus/environment/benchmark freshness, and fails closed on any gap | §6 |
| Tampering with a persisted receipt on disk after the fact | `receipt_id` is a deterministic content digest; the release gate recomputes it and rejects any mismatch | §6, `compute_receipt_digest` |

## 2. Resource and capability policy

Every external executable path, timeout, CPU/memory budget, process-count
budget, and network-access decision is required to flow through one of
two operator-controlled dataclasses — nothing in the pipeline hard-codes a
looser value than these:

- `ipfs_datasets_py.logic.hammers.models.HammerPolicy` — per-request
  budgets (`timeout_seconds`, `cpu_seconds`, `memory_mb`,
  `network_allowed`), the solver allow-list (`allowed_solvers`, which must
  be a subset of `policy.known_solver_names()`), and every opt-in flag
  (`allow_learned_premise_selector`, `allow_llm_premise_ranking`,
  `allow_native_automation_fallback`, `allow_llm_decomposition_hints`).
- `ipfs_datasets_py.logic.hammers.policy.PortfolioPolicy` — the owning
  `HammerPolicy` plus per-solver `SolverBudget` overrides,
  `executable_overrides` (explicit paths, still validated to exist/be
  executable and still gated by `allowed_solvers`), `max_parallel_
  processes`, and the cancellation policy (`cancel_on_first_conclusive`).

CPU and memory budgets are enforced with POSIX `RLIMIT_CPU`/`RLIMIT_AS` in
the child process's `preexec_fn` (`policy.build_preexec_fn`) as the
authoritative backstop, in addition to any solver-specific CLI timeout
flag — a solver that ignores its own `--timeout` argument is still killed
by the OS-level rlimit and the wall-clock subprocess deadline. See
`docs/logic/itp_hammer_user_guide.md` §5 for the concrete default values.

## 3. Confirmation gate for native process launch

Three operations spawn a real external process: `inspect` (a native
`lean`/`coqtop`/`isabelle` process for goal capture, HAMMER-006),
`run-candidate` (external solver processes, HAMMER-008), and
`reconstruct` (a native ITP kernel check, HAMMER-010). Each requires an
explicit `confirm_native_execution: bool = True` (CLI: `--confirm`; MCP:
the same parameter). Without it, the call returns a structured
`confirmation_required` response and **launches nothing** — no
subprocess, no temp file beyond what capability discovery already
performed. `select-premises`, `translate`, `retrieve-receipt`, and
`persist-receipt` are pure in-process computation or local-disk/IPFS I/O
and carry no such parameter, because there is nothing to confirm. See
`docs/logic/itp_hammer_mcp_contract.md` §2.2 for the full response schema.

## 4. Subprocess construction discipline

Every subprocess invocation in this pipeline (portfolio solver execution,
ITP frontend goal capture, ITP kernel reconstruction) is built as an
explicit argv list passed to `subprocess.run`/`subprocess.Popen` — never
`shell=True`, and never a string built by concatenating user/corpus
content. Goal/candidate/premise content reaches the subprocess only via a
file path (the caller's translated/reconstructed text is written to a
temp file first); the subprocess's command line itself carries only a
resolved executable path, fixed flags, and that file path. This means a
theorem statement, premise text, or solver trace containing shell
metacharacters, path traversal sequences, or other adversarial content
cannot alter what command is executed — it can, at most, cause the
*content* of the invoked tool's own input to be malformed, which the tool
itself (or this pipeline's own translation/reconstruction validation)
rejects.

Executable resolution (`shutil.which`, or an explicit,
still-validated-to-exist `PortfolioPolicy.executable_overrides` entry)
always happens before invocation and is itself gated by the
`HammerPolicy.allowed_solvers` allow-list — an operator cannot be tricked
into running an arbitrary executable path supplied inside a request
payload.

## 5. The verification trust boundary

This is the single most important invariant in the whole pipeline, and it
is enforced in code, not just documentation:

```
HammerResultStatus.VERIFIED  ⟺  reconstruction is not None
                              AND reconstruction.kernel_accepted is True
```

`ipfs_datasets_py.logic.hammers.models.HammerResult.__post_init__`
enforces both directions of this equivalence at construction time — it is
impossible to construct a `HammerResult` with `status=VERIFIED` and no (or
a failed) kernel reconstruction, and impossible to construct one with a
successful kernel reconstruction that is not reflected as `VERIFIED`.
`HammerReceipt.validate()` (HAMMER-012) re-checks this on every persisted
receipt, and the release gate (`scripts/ops/logic/
release_itp_hammer_gate.py`, §6 below) independently re-verifies it again
for every receipt a release references, on the assumption that a
persisted JSON file could in principle be hand-edited after the fact.

A solver's own verdict — `proved`, `disproved`, `sat`, `unsat` — never
appears as a `HammerResult.status` value. It can only ever produce a
`ProofCandidateRecord` (untrusted) or, for a refutation, contribute to a
`counterexample` result — both of which remain explicitly unverified.

## 6. Release gate checks (fail-closed)

`scripts/ops/logic/release_itp_hammer_gate.py` (default, no `--generate`)
loads `data/logic/itp_hammer/release-evidence.json` and runs the
following checks. **Any single failure fails the whole gate** (exit code
1, structured JSON failure report); there is no partial-pass state, and
any unexpected exception (a missing file, a parse error, an
unreconstructable record) is caught and reported as a failure rather than
propagating as an uncaught traceback — the gate cannot accidentally exit
`0` on an error path.

| # | Check | Fails closed when |
|---|---|---|
| 1 | `schema_version` | The evidence file's schema version is not the one this gate understands |
| 2 | `corpus_lock_present` | `corpus_lock.manifest_id`/`.revision` are missing/empty, or `theorem_count` is not a positive integer — **missing corpus lock** |
| 3 | `environment_lock_present` / `_schema` / `_not_stale` / `_matches_source` | `data/logic/itp_hammer/environment.json` (or the path the evidence references) is missing, malformed, older than `--max-environment-lock-age-days` (default 180), or its summary has drifted from the evidence's embedded copy — **missing/stale environment lock** |
| 4 | `benchmark_report_present` / `_not_stale` | The referenced `benchmark.json` is missing, malformed, or older than `--max-benchmark-age-days` (default 30) |
| 5 | `golden_report_present` / `_kernel_proof` / `_corpus_consistency` | The referenced `golden-report.json` is missing/malformed, records zero `verified` cases, or claims `verified` for any case without a `kind == "real_kernel"` and `kernel_accepted == true` record — **absent kernel proof** |
| 6 | `receipts_store_present` / `receipts_present` | The receipt store root directory or the evidence's `receipts` list is missing/empty |
| 7 | `receipt[*].loadable` | A referenced `receipt_id` cannot be reloaded from the recorded `ReceiptStore` root — **missing receipt evidence** |
| 8 | `receipt[*].trust_contract_valid` | The reloaded receipt fails `HammerReceipt.validate()` (re-running every HAMMER-001/012 coherence and trust-boundary check) |
| 9 | `receipt[*].not_tampered` | `compute_receipt_digest(receipt)` does not match the receipt's own `receipt_id` — **tamper detection** |
| 10 | `receipt[*].corpus_revision_consistent` | The receipt's `corpus_revision` does not match the release's `corpus_lock.revision` |
| 11 | `receipt[*].not_stale` | The receipt's `created_at` is older than `--max-receipt-age-days` (default 90) — **stale receipt** |
| 12 | `receipt[*].status_matches_manifest` | The receipt's actual status has drifted from what the evidence manifest claims for that case |
| 13 | `receipt[*].kernel_acceptance_evidence` | A receipt claims `status == "verified"` without a `kernel_accepted == True` `ReconstructionRecord` — **verified result without kernel acceptance evidence** |
| 14 | `at_least_one_kernel_checked_verified_receipt` | Zero receipts are both `verified` and kernel-accepted — a release must demonstrate at least one actual kernel-checked theorem |

`--generate` mode builds these receipts fresh from the same HAMMER-014
golden-case builders the end-to-end test suite uses, so a freshly
generated evidence file is expected to pass every check above
immediately; the checks exist to catch **drift** between generation time
and validation time (an environment that has aged out, a receipt that has
gone stale, a hand-edited or corrupted file) — exactly the gap between "we
generated evidence once" and "this evidence is still trustworthy right
now."

## 7. LLM-assisted operation boundaries

Where enabled (never by default), an LLM may:

- Propose a premise ranking (`HammerPolicy.allow_llm_premise_ranking`).
- Suggest subgoal statements for the HAMMER-011 decomposition plan
  (`HammerPolicy.allow_llm_decomposition_hints`).

An LLM may **never**:

- Supply an accepted proof, or cause a result to reach `VERIFIED` without
  an actual kernel reconstruction (enforced structurally — see §5, not by
  policy convention).
- Suppress or downgrade an `unsupported_translation` result.
- Bypass the `confirm_native_execution` gate (§3) for any operation that
  launches a real process.

Every LLM-suggested decomposition subgoal is redacted
(`redacted_suggestion` placeholder), requires explicit human review before
being acted on, and remains untrusted until its own native reconstruction
independently passes the target ITP kernel — identical to any other
untrusted candidate in this pipeline.

## 8. Privacy and data handling

See `docs/logic/itp_hammer_user_guide.md` §8 for the user-facing summary.
From a security standpoint, the two receipt views have different exposure
profiles:

- **Full receipt** (`HammerReceipt.to_dict()`): contains private theorem
  text, translated formulas, reconstructed native source, and raw
  kernel/solver stdout/stderr. Treat as sensitive; local-disk storage
  defaults to `~/.cache/ipfs_datasets_py/hammer_receipts` (or
  `IPFS_DATASETS_PY_HAMMER_RECEIPTS_DIR`), not a world-readable location,
  and IPFS publication is opt-in (`use_ipfs=True` or an injected backend).
- **Publishable receipt** (`HammerReceipt.to_publishable_dict()`):
  redacts every private-content field to a `<redacted:label length=N
  digest=...>` placeholder and scrubs credential-shaped strings from every
  remaining leaf, including caller metadata and diagnostic notes. This is
  the only form intended for external sharing; it retains the fields a
  release gate needs (`status`, `kernel_accepted`, `corpus_revision`,
  `created_at`) precisely because those are not private content.
- Release evidence (`data/logic/itp_hammer/release-evidence.json`)
  embeds only receipt ids, status/kernel-acceptance metadata, corpus
  revision, and timestamps — never goal text, translated formulas, or raw
  kernel/solver output.

## 9. Limitations of this security model

- Resource limits (`RLIMIT_CPU`/`RLIMIT_AS`) are POSIX-only; on
  non-POSIX platforms only the wall-clock subprocess timeout applies as a
  backstop.
- The pipeline trusts the *installed* ITP kernel/solver binaries
  themselves to behave as documented (e.g., that `lean`'s kernel check
  genuinely fails on an invalid proof term). Supply-chain integrity of
  those binaries (verifying `lean`/`coqtop`/`z3`/etc. themselves have not
  been tampered with) is outside this pipeline's scope — the environment
  lock (HAMMER-002) records *versions and paths*, not binary signatures.
- The release gate validates *this pipeline's own* receipts and
  artifacts; it does not audit the correctness of the corpus content
  itself (a maliciously mislabeled but internally-consistent theorem
  statement, for example) beyond the corpus's own duplicate-identity and
  license-metadata checks (HAMMER-003).
