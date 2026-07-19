# ITP Hammer Capability Inventory

Status: Implemented (HAMMER-002)
Date: 2026-07-19
Script: `scripts/ops/logic/probe_itp_hammer_environment.py`
Generated artifact: `data/logic/itp_hammer/environment.json`
Tests: `tests/unit_tests/logic/hammers/test_environment_probe.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (`## HAMMER-002`, the
taskboard entry this document is an output of), `docs/logic/itp_hammer_contract.md`
(the trust contract this inventory feeds).

## 1. Purpose

Before any premise selection, translation, or portfolio execution can be
built (HAMMER-003 onward), the pipeline needs a deterministic, offline
answer to one question: **what Lean, Coq/Rocq, Isabelle, Z3, CVC5, Vampire,
E, TPTP, SMT-LIB, TDFOL, CEC, and prover-installer surfaces already exist —
right now, in this checkout and this environment?**

This document is the narrative summary of that inventory. The authoritative,
machine-readable answer is produced by
`scripts/ops/logic/probe_itp_hammer_environment.py` and written to
`data/logic/itp_hammer/environment.json`. Re-run the script any time the
toolchain or repository changes; the JSON file checked into this repository
is a point-in-time snapshot, not a guarantee about every future environment.

## 2. Non-negotiable constraints

Per the HAMMER-002 acceptance criteria, the probe:

- **Never installs anything.** It performs pure discovery: `shutil.which`
  plus a small, fixed list of well-known user-local install directories
  (`~/.local/bin`, `~/.elan/bin`, `~/.opam/default/bin`, and the
  `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT`-configurable prover root used by
  `ipfs_datasets_py.logic.external_provers.lazy_installer`). It does not
  call `pip install`, `opam install`, `elan`, `apt`, or any installer
  script, ever.
- **Never invokes a solver by default.** The only subprocess execution the
  script ever performs is a single, bounded (5 second timeout)
  `--version`-style metadata query, and only for an executable that
  discovery already found on disk. That query never runs a proof search,
  never reads or writes a problem file, and can be disabled entirely with
  `--no-version-probe` (or `probe_version=False` when calling
  `build_environment_report` from Python) for a fully hermetic run that
  performs **zero** subprocess calls.
- **Never imports `ipfs_datasets_py`.** "Parser support" / "native
  proof-trace support" / "installer support" evidence for in-repo surfaces
  is gathered via static filesystem presence checks (`Path.is_file()`)
  against known relative paths, not by importing the corresponding module.
  This keeps the probe fast (well under a second) and free of any import-time
  side effects from the wider package (optional-dependency shims, the
  lazy installer's own state, or unrelated auto-installer behavior in
  `ipfs_datasets_py/__init__.py`).
- **Records an explicit unavailable state for everything that is missing.**
  Every surface reports `available: bool` and, whenever that is `False`, a
  non-empty, machine-readable `unavailable_reason` (a `;`-joined list of
  reason codes such as `z3_executable_not_found_on_path_or_common_install_dirs`
  or `no_isabelle_bridge_or_frontend_module_in_repo`). Nothing is silently
  omitted, and `unavailable_reason` is always `None` when `available` is
  `True` (enforced by `test_unavailable_reason_is_explicit_iff_unavailable`).

## 3. Report schema

`build_environment_report()` (and the CLI's `--out` file) return/write a
JSON document shaped like:

```json
{
  "schema_version": "itp-hammer-environment-probe/v1",
  "generated_at": "2026-07-19T08:21:30Z",
  "probe_options": {
    "version_probe_enabled": true,
    "install_attempted": false,
    "solver_invoked": false
  },
  "surfaces": {
    "<surface_id>": {
      "surface_id": "...",
      "display_name": "...",
      "category": "interactive_theorem_prover | automated_theorem_prover | smt_solver | translation_format | native_logic_framework | prover_installer",
      "executables": { "<name>": { "candidates": [...], "resolved_name": ..., "resolved_path": ..., "found": bool, "version_probe_attempted": bool, "version_command": [...] | null, "version": "..." | null, "version_probe_error": "..." | null } },
      "repo_modules": [ { "path": "ipfs_datasets_py/...", "kind": "bridge|adapter|parser|writer|...", "exists": bool } ],
      "native_proof_trace_support": { "supported": bool, "mechanism": "...", "evidence": ["..."] },
      "parser_support": { "supported": bool, "mechanism": "...", "evidence": ["..."] },
      "available": bool,
      "unavailable_reason": "..." | null,
      "notes": "..."
    }
  },
  "summary": {
    "surface_count": 12,
    "available_count": 8,
    "unavailable_count": 4,
    "unavailable_surfaces": ["e", "isabelle", "vampire", "z3"]
  }
}
```

`available` for an executable-backed surface (Lean, Coq/Rocq, Isabelle, Z3,
CVC5, Vampire, E) requires **both** an executable being found **and** a
corresponding repository bridge/adapter module existing — a bare executable
with no in-repo code path to drive it is not yet an operational surface for
the hammer pipeline, and vice versa.

## 4. Surface-by-surface findings

The following reflects the snapshot in `data/logic/itp_hammer/environment.json`
at authoring time (regenerate to get current values for any given machine).

### 4.1 Interactive Theorem Provers (ITPs)

| Surface | Executable(s) found | Version (this snapshot) | Repo bridge/adapter | Native proof-trace mechanism | Available |
|---|---|---|---|---|---|
| `lean` | `lean`, `lake` (elan-managed) | Lean 4.31.0 / Lake 5.0.0 | `ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py` | Lean kernel type-checks elaborated terms; `lean`/`lake build` exit code is the trust boundary | Yes |
| `coq` | `coqc`, `coqtop` (Rocq 9.x rebrand; `rocq` binary name not present) | Rocq 9.1.1 (OCaml 4.14.2) | `ipfs_datasets_py/logic/external_provers/interactive/coq_prover_bridge.py` | Coq/Rocq kernel re-checks compiled `.vo` proof terms | Yes |
| `isabelle` | none | — | **none** | Isabelle's LCF-style kernel supports native proof-term checking *in principle*, but no bridge/frontend exists in this repository | **No** |

Neither `lean_prover_bridge.py` nor `coq_prover_bridge.py` yet implements
the HAMMER-006 native goal/hypothesis snapshot frontend
(`ipfs_datasets_py/logic/hammers/frontends/{lean,coq,isabelle}.py`) — that
taskboard entry is still `waiting`. Today's bridges wrap invocation and
result parsing only. Isabelle has neither an executable nor any bridge code
at all, so it is the one ITP marked fully `unavailable`.

### 4.2 SMT Solvers

| Surface | Executable found | Python binding | Version (this snapshot) | Repo bridge | Available |
|---|---|---|---|---|---|
| `z3` | no | no (`z3` package not importable) | — | `ipfs_datasets_py/logic/external_provers/smt/z3_prover_bridge.py`, `.../security_models/crypto_exchange/compilers/to_z3.py` | **No** |
| `cvc5` | yes | no (`cvc5` package not importable) | cvc5 1.3.2 | `ipfs_datasets_py/logic/external_provers/smt/cvc5_prover_bridge.py`, `.../security_models/crypto_exchange/runners/cvc5_runner.py` | Yes |

Z3 has full bridge/compiler support in the repository, but this particular
environment snapshot has neither the `z3` CLI nor the `z3` python package
installed, so it is `unavailable` here even though the code that would use
it exists. CVC5's CLI is present and paired with existing bridge code, so it
is `available`.

### 4.3 Automated Theorem Provers (ATPs)

| Surface | Executable found | Repo adapter | Native proof-trace mechanism | Available |
|---|---|---|---|---|
| `vampire` | no | `ipfs_datasets_py/logic/CEC/provers/vampire_adapter.py` | TPTP/TSTP derivation via `--proof tptp --output_axiom_names on` | **No** |
| `e` | no (`eprover`/`eprover-ho`/`E`) | `ipfs_datasets_py/logic/CEC/provers/e_prover_adapter.py` | TSTP proof object via `--tstp-out`/`--proof-object` | **No** |

Both Vampire and E already have full CEC-side adapters (TPTP problem
construction + subprocess invocation + result parsing), but neither
executable is present in this environment snapshot.

### 4.4 Translation formats

| Surface | Writer | Parser | Available | Gap |
|---|---|---|---|---|
| `tptp` | `ipfs_datasets_py/logic/CEC/provers/tptp_utils.py` | `ipfs_datasets_py/logic/CEC/native/problem_parser.py` (`TPTPFormula`) | Yes | Optional reference tool `tptp4X` is not present, but is not required for in-repo reader/writer support |
| `smtlib` | `ipfs_datasets_py/logic/security_models/crypto_exchange/compilers/to_smtlib.py`, `ipfs_datasets_py/logic/integration/converters/logic_translation_core.py` (`SMTTranslator`) | **none** | Yes (writer only) | **Explicit gap:** the repository only ever *generates* SMT-LIB2 text (via Python term construction and the z3/cvc5 python APIs); there is no standalone reader for arbitrary external `.smt2` input. This is a concrete input for HAMMER-007 (typed translation to TPTP and SMT-LIB). |

TPTP has both directions (read and write); SMT-LIB currently has only a
writer. The probe surfaces this asymmetry explicitly via
`parser_support.supported == false` on the `smtlib` surface so HAMMER-007
does not have to rediscover it.

### 4.5 Native, in-repo logic frameworks

| Surface | Core module(s) | Native prover | Parser | Available |
|---|---|---|---|---|
| `tdfol` | `ipfs_datasets_py/logic/TDFOL/tdfol_core.py` | `ipfs_datasets_py/logic/TDFOL/tdfol_prover.py` (forward/backward chaining, modal tableaux, temporal/deontic reasoning; produces `ProofResult`/`ProofStep` records defined in `tdfol_core.py`) | `tdfol_parser.py` (symbolic/NL/JSON), `tdfol_dcec_parser.py` (DCEC bridge), `tdfol_converter.py` (round-trip to TPTP/SMT-LIB text) | Yes |
| `cec` | `ipfs_datasets_py/logic/CEC/native/dcec_core.py` | `ipfs_datasets_py/logic/CEC/native/prover_core.py` (native inference-rule engine, documented as covering 87 rules), `ipfs_datasets_py/logic/CEC/native/shadow_prover.py` (ShadowProver-style modal search); `ipfs_datasets_py/logic/CEC/provers/prover_manager.py` additionally coordinates external Z3/Vampire/E attempts | `ipfs_datasets_py/logic/CEC/native/problem_parser.py` | Yes |

TDFOL and CEC are pure-Python, in-repo logic frameworks. Their "availability"
is a static source-file presence check, not an external executable/install
check — they are always available wherever this checkout is available.
`cec`'s `prover_manager.py` is also the integration point that dispatches to
the external `vampire`/`e` ATP adapters inventoried in §4.3 above.

### 4.6 Prover-installer surfaces

| Module | Role |
|---|---|
| `ipfs_datasets_py/logic/external_provers/lazy_installer.py` | Opt-in, single best-effort install for a *requested* prover. Gated by `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS` / per-prover `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>` env vars; disabled unless explicitly enabled (Coq additionally defaults to disabled even when the global switch is on). Exposes `find_executable()`, which this probe's own executable discovery deliberately mirrors (same search directories) without importing the module. |
| `ipfs_datasets_py/logic/integration/bridges/prover_installer.py` | The same installer behavior, exposed as the `ipfs-datasets-install-provers` console script and via `setup.py` post-install hooks (also opt-in). |
| `ipfs_datasets_py/logic/external_provers/prover_router.py` | Runtime discovery/selection among already-installed provers — does not install anything itself. |

This inventory records that these installer surfaces **exist** in the
repository; it never calls any of them. Installation remains a strictly
separate, explicitly-opted-into action from environment discovery.

## 5. How to regenerate the inventory

```bash
# Full probe (includes bounded --version metadata queries for anything found):
PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py \
  --out data/logic/itp_hammer/environment.json

# Fully hermetic probe (zero subprocess calls):
PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py \
  --no-version-probe --out /tmp/environment.json
```

Both invocations are safe to run repeatedly and in CI: they never modify
the toolchain, never touch the network, and never run a proof search.

## 6. Consequences for later taskboard items

- **HAMMER-003** (content-addressed premise corpus): no direct dependency,
  but corpus ingestion should record which ITP a theorem came from using the
  same `ITPKind` values already defined in `ipfs_datasets_py/logic/hammers/models.py`
  (`lean`, `coq`, `isabelle`), consistent with this inventory's surface ids.
- **HAMMER-006** (native ITP frontend adapters): Lean and Coq/Rocq already
  have lower-level bridges to build on; Isabelle has nothing and will need a
  frontend built from scratch, confirmed unavailable here.
- **HAMMER-007** (typed translation to TPTP/SMT-LIB): the SMT-LIB
  parser gap identified in §4.4 is a direct, actionable input.
- **HAMMER-008** (policy-controlled solver portfolio): only `cvc5` (and the
  in-repo `cec`/`tdfol` native provers) are `available` end-to-end in this
  snapshot; `z3`, `vampire`, and `e` have code but no local executable, and
  the portfolio's allowlist/policy layer should treat "surface unavailable"
  (from this inventory) as equivalent to "excluded from this run's
  portfolio," not as an error.
