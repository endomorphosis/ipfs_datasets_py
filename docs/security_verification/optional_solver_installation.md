# Optional Solver Installation and Lane Policy

Status: active
Task: `PORTAL-CXTP-086`
Date: 2026-07-08

## Purpose

The crypto-exchange proof workflow has optional solver lanes for Apalache,
Tamarin, ProVerif, Lean, and Coq. Optional does not mean invisible. A missing
optional solver must be recorded as either a `degraded` proof lane on a
supported host or a `blocked` proof lane on an unsupported or unusable host.
No release evidence may claim coverage from a lane whose status is not
`ready`.

Use:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/install_optional_theorem_solvers.py
```

The script writes:

```text
security_ir_artifacts/environment/optional-solver-install-report.json
```

The default mode is probe-and-plan only. It runs version probes and emits
reviewed command plans; it does not install packages.

## Lane Outcomes

The report uses these lane outcomes:

| Status | Meaning | Release effect |
| --- | --- | --- |
| `ready` | The solver executable resolved and its version probe passed. | The lane may claim coverage after proof artifacts are actually produced. |
| `degraded` | The solver is missing on a supported Linux/macOS proof worker. | The lane is explicit reduced coverage and maps to `missing-solver` for any claim requiring that lane. |
| `blocked` | The host platform is unsupported or a discovered executable failed its probe. | The lane must not run or claim coverage until remediated. |

Global proof acceptance still follows
`docs/security_verification/production_release_decision_policy.md`: any
required claim that depends on a missing solver is `missing-solver` and
therefore `blocked-production`.

## Supported Platforms

Native optional-solver installation is approved for:

- Linux on `x86_64`, `amd64`, `aarch64`, or `arm64`.
- macOS on `x86_64`, `amd64`, `aarch64`, or `arm64`.

Windows-native workers are recorded as unsupported for these lanes. Use WSL2
or a Linux release worker and attach the Linux probe report instead of
treating native Windows absence as optional success.

## Safe Operating Rules

- Keep `PYTHONPATH="$PWD"` while generating reports.
- Prefer user-scoped package managers such as conda, Homebrew/Linuxbrew, OPAM,
  Nix, or elan over ad hoc system mutation.
- Commands marked `requires_privilege` require OS-owner approval before use.
- Commands marked `requires_network` must run only on workers allowed to fetch
  reviewed upstream packages.
- For release workers, pin versions and retain checksums in the evidence
  bundle. The installer report records command plans, not supply-chain review.
- Rerun both this installer report and
  `scripts/ops/security_verification/probe_theorem_prover_environment.py`
  after any installation.

## Apalache

Lane: `tla_apalache_state_machine`

Use Apalache for TLA+/temporal workflow and interleaving checks. The upstream
Apalache documentation describes three installation paths: prebuilt JVM
package, Docker, and source builds. For this repository, prefer a reviewed
prebuilt JVM package on Linux/macOS and keep the launcher on `PATH`.

Safe install plan:

```bash
conda install -c conda-forge openjdk=17
install -d "$HOME/.local/opt/apalache" "$HOME/.local/bin"
tar -xzf "$APALACHE_TGZ" -C "$HOME/.local/opt/apalache" --strip-components=1
ln -sf "$HOME/.local/opt/apalache/bin/apalache-mc" "$HOME/.local/bin/apalache-mc"
```

Probe:

```bash
java -version
apalache-mc version
```

If Apalache is missing on a supported host, keep the lane `degraded`. If the
platform is unsupported or the launcher exists but fails, keep the lane
`blocked`.

Reference: <https://apalache-mc.org/docs/apalache/installation/index.html>

## Tamarin

Lane: `tamarin_symbolic_protocol`

Use Tamarin for symbolic protocol proofs of custody, signing authority, replay,
and capability flows. The Tamarin manual recommends Homebrew on Linux/macOS and
also documents Nix and direct binary/source paths.

Safe install plan:

```bash
brew install tamarin-prover/tap/tamarin-prover
```

Alternative Nix-managed Linux worker:

```bash
nix-env -iA nixpkgs.tamarin-prover
```

Probe:

```bash
tamarin-prover --version
```

If Tamarin is missing, protocol coverage is `degraded`; do not claim
Tamarin-backed evidence. If Tamarin is required by a production claim, the
claim outcome is `missing-solver`.

Reference: <https://tamarin-prover.com/manual/master/book/002_installation.html>

## ProVerif

Lane: `proverif_symbolic_protocol`

Use ProVerif for symbolic reachability and secrecy checks. ProVerif is normally
installed through OPAM into a controlled OCaml switch.

Safe install plan:

```bash
conda install -c conda-forge opam ocaml
opam update
opam install -y proverif
```

macOS prerequisite option:

```bash
brew install opam ocaml
opam update
opam install -y proverif
```

Probe:

```bash
proverif -version
```

Missing ProVerif is a `degraded` protocol lane on supported hosts and a
`missing-solver` outcome for any claim that requires ProVerif evidence.

Reference: <https://bblanche.gitlabpages.inria.fr/proverif/>

## Lean

Lane: `lean_proof_consumer_invariants`

Use Lean for proof-consumer invariants and receipt/canonicalization checks. The
Lean project recommends editor-assisted setup for interactive work; release
workers should use reviewed elan installation and keep `lean` and `lake` on
`PATH`.

Safe install plan:

```bash
curl -fsSLo /tmp/elan-init.sh https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh
sh /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:stable
export PATH="$HOME/.elan/bin:$PATH"
```

Probe:

```bash
lean --version
lake --version
```

Missing Lean is a `degraded` proof-assistant lane unless a production task
requires Lean-checked evidence, in which case the dependent claim is
`missing-solver`.

Reference: <https://lean-lang.org/install/>

## Coq

Lane: `coq_proof_consumer_invariants`

Use Coq for independent proof-consumer invariant checking. The Coq/Rocq
documentation recommends the Coq Platform with OPAM for managed package sets;
this repository also accepts controlled conda, Homebrew, or reviewed OS
packages for probeable release workers.

Safe install plan:

```bash
conda install -c conda-forge coq
```

Alternative OPAM plan:

```bash
opam update
opam install -y coq
```

Debian/Ubuntu plan requiring OS-owner approval:

```bash
sudo apt-get update
sudo apt-get install -y coq
```

Probe:

```bash
coqc --version
coqtop --version
```

Missing Coq is a `degraded` proof-assistant lane on supported hosts. It blocks
only claims that explicitly require Coq evidence.

Reference: <https://rocq-prover.org/doc/V8.17.1/refman/practical-tools/utilities.html>

## Refresh Procedure

Run the optional installer report:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --out security_ir_artifacts/environment/optional-solver-install-report.json
```

Run the baseline dependency probe:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_theorem_prover_environment.py \
  --out security_ir_artifacts/environment/solver-dependency-probe.json
```

Interpretation:

- `ready` lanes may be used only when proof artifacts for that lane are also
  present and reviewed.
- `degraded` lanes are explicit coverage gaps and must be mentioned in proof
  receipts.
- `blocked` lanes must be remediated or moved to a supported worker before the
  lane can contribute evidence.
