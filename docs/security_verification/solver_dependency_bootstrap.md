# Solver Dependency Bootstrap Runbook

Status: active
Task: `PORTAL-CXTP-058`
Date: 2026-07-08

## Purpose

The crypto exchange theorem-prover workflow is fail-closed. This runbook
defines the host dependency baseline for solver-backed security verification
and explains how to interpret
`scripts/ops/security_verification/probe_theorem_prover_environment.py`.

The probe is the operational authority for the current checkout. This document
is the bootstrap and incident runbook: use it to provision the environment,
run the probe, and decide whether a missing dependency blocks proof acceptance
or only records a reduced optional capability.

## Supported Host Profile

Use a dedicated Linux or macOS worker for release proofs. Linux x86_64 is the
preferred production profile because Z3, CVC5, Apalache, Tamarin, ProVerif,
Lean, and Coq all have practical package-manager or release-binary paths there.

Minimum host requirements:

- OS: Linux x86_64 preferred; macOS arm64/x86_64 acceptable for developer
  probes when every required solver is explicitly available.
- CPU: 2 cores minimum, 4 or more recommended for parallel solver runs.
- Memory: 8 GiB minimum, 16 GiB recommended for Apalache/Tamarin workloads.
- Disk: 10 GiB free minimum for Python wheels, Node packages, JVM tools,
  theorem prover packages, temporary proof files, and solver logs.
- Shell: POSIX shell with `bash`, `find`, `grep`/`rg`, `tar`, `unzip`, and
  `curl` or `wget` available.
- Network: required for first-time dependency installation; not required for a
  fully provisioned offline proof worker.

Do not accept a production proof generated on a host whose architecture differs
from the reviewed release profile unless the probe result and proof receipt
make that difference explicit.

## Python Baseline

The probe requires a working Python interpreter and records the interpreter used
to execute the probe. Use the same interpreter for package installation,
probes, proof scripts, and tests. The current probe records Python `>=3.10` as
the minimum runtime baseline; the validation command for this task uses
`/home/barberb/miniforge3/bin/python`.

Recommended bootstrap:

```bash
cd /home/barberb/barberb/copilot-worktrees/lift_coding/hallucinate-llc-psychic-adventure/external/ipfs_datasets
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[logic,test]'
```

Validate the interpreter:

```bash
python --version
```

## Node, npm, and TypeScript

The security IR workflow includes TypeScript schema/compiler checks. Provision
Node.js and npm before running the probe so TypeScript availability is measured
from the same `PATH` used by proof scripts.

Production baseline:

- Node.js: current LTS release line or newer release accepted by the security
  verification scripts.
- npm: the npm version bundled with that Node.js release, or a newer compatible
  npm.
- TypeScript compiler: `tsc` on `PATH`, commonly installed with
  `npm install -g typescript`.

Validation commands:

```bash
node --version
npm --version
tsc --version
```

If the worker uses a per-repository Node install, ensure `node_modules/.bin` is
on `PATH` before running the probe:

```bash
export PATH="$PWD/node_modules/.bin:$PATH"
```

## Solver and Tool Requirements

The probe separates hard release requirements from optional capability checks.
Use the probe output for the current required/optional classification.

### Z3

The probe checks the `z3` executable. Keep the executable on `PATH`, or set
`Z3_EXE` to an explicit executable path for reproducible proof workers.

Install:

```bash
# Conda example
conda install -c conda-forge z3

# Debian/Ubuntu example
sudo apt-get update && sudo apt-get install -y z3
```

Validate:

```bash
z3 --version
```

### CVC5

The probe checks the `cvc5` executable. Keep the executable on `PATH`, or set
`CVC5_EXE` to an explicit executable path for differential SMT workers.

Install:

```bash
# Conda example
conda install -c conda-forge cvc5

# User-local binary example after downloading a reviewed release artifact
install -m 0755 cvc5 "$HOME/.local/bin/cvc5"
```

Validate:

```bash
cvc5 --version
```

### Apalache

Apalache is a JVM-based TLA+ model checker used for temporal/state-machine
coverage when a task or release gate requires it. It requires a Java runtime
compatible with the installed Apalache release.

Install from the Apalache release artifacts or a controlled package-manager
mirror, then put the `apalache-mc` launcher on `PATH`.

Validate:

```bash
java -version
apalache-mc version
```

Missing Apalache blocks only checks that the probe marks required. If it is
reported as optional, record the capability gap and do not claim Apalache-backed
temporal model coverage in the proof receipt.

### Tamarin

Tamarin is used for protocol and adversary-model proofs when the current
security plan requires symbolic protocol analysis.

Install from the Tamarin distribution or a controlled OS/package-manager
source. Ensure `tamarin-prover` is on `PATH`.

Validate:

```bash
tamarin-prover --version
```

If Tamarin is optional in the probe output, its absence reduces protocol-proof
coverage only. Do not promote protocol claims that depend on Tamarin evidence.

### ProVerif

ProVerif is used for cryptographic protocol reachability and secrecy checks
when explicitly required by the security verification task.

Install from the ProVerif distribution, OPAM, or a controlled package-manager
source. Ensure `proverif` is on `PATH`.

Validate:

```bash
proverif -version
```

If ProVerif is optional in the probe output, its absence is a recorded
capability gap and not a proof-acceptance blocker by itself.

### Lean

The probe checks the `lean` executable. Lean is an interactive proof-assistant
capability for higher-order or dependent-type evidence. Set `LEAN_EXE` when the
release worker should use a pinned Lean executable outside `PATH`.

Install with elan or the repository installer:

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
export PATH="$HOME/.elan/bin:$PATH"
```

Validate:

```bash
lean --version
lake --version
```

If Lean is optional, do not claim Lean-checked proofs in release evidence when
it is missing. If the probe marks Lean required, missing `lean` blocks proof
acceptance.

### Coq

The probe checks the `coqc` executable. Coq is an interactive proof-assistant
capability and normally comes from an OS package manager, Homebrew,
conda-forge, or OPAM. Set `COQC_EXE` when the release worker should use a
pinned Coq compiler outside `PATH`.

Install examples:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y coq

# macOS
brew install coq

# OPAM
opam init -y
opam install -y coq
```

Validate:

```bash
coqc --version
coqtop --version
```

If Coq is optional, missing Coq is not a global release blocker. It does block
any claim that the evidence packet contains Coq-checked proof artifacts.

## Environment Variables

Set these variables explicitly in CI/release workers so the probe observes the
same environment as proof execution:

```bash
export PYTHONPATH="$PWD"
export PATH="$PWD/node_modules/.bin:$HOME/.local/bin:$HOME/.elan/bin:$HOME/.opam/default/bin:$PATH"
```

The probe treats `PATH` and `PYTHONPATH` as required. It records hashes and
lengths for environment variable values so the artifact can prove presence
without storing full local path lists.

Optional executable override variables:

- `Z3_EXE`
- `CVC5_EXE`
- `APALACHE_EXE`
- `TAMARIN_EXE`
- `PROVERIF_EXE`
- `LEAN_EXE`
- `COQC_EXE`

Optional toolchain variables:

- `JAVA_HOME`
- `COQPATH`
- `LEAN_PATH`

## Running the Probe

Run the probe from the repository root with the same interpreter and `PATH`
used for proof generation:

```bash
cd /home/barberb/barberb/copilot-worktrees/lift_coding/hallucinate-llc-psychic-adventure/external/ipfs_datasets
. .venv/bin/activate
export PYTHONPATH="$PWD"
export PATH="$PWD/node_modules/.bin:$HOME/.local/bin:$HOME/.elan/bin:$HOME/.opam/default/bin:$PATH"

PYTHONPATH=. python scripts/ops/security_verification/probe_theorem_prover_environment.py
```

Before changing CI or release automation, inspect the probe's supported flags:

```bash
PYTHONPATH=. python scripts/ops/security_verification/probe_theorem_prover_environment.py --help
```

Write the result to the security verification artifact directory named by this
task:

```bash
PYTHONPATH=. python scripts/ops/security_verification/probe_theorem_prover_environment.py \
  --out security_ir_artifacts/environment/solver-dependency-probe.json
```

By default the script exits `0` when it can write a report, even if the report
contains blocking evidence. Use `--fail-on-blocking` in CI jobs that should
fail immediately when required dependencies are absent.

Do not update proof baselines, solver artifacts, or retention baselines merely
because the probe reports missing tools.

## Interpreting Probe Results

Treat the probe as a release gate, not as a suggestion list.

Blocking conditions:

- The probe reports `proof_acceptance_blocked: true`.
- The probe reports a required solver, runtime, compiler, or OS/CPU property as
  unavailable.
- The probe cannot execute or cannot emit parseable output.
- A required solver is present but fails its smoke/version command.
- The environment differs from the release profile in a way the probe marks
  blocking.

When any blocking condition occurs:

1. Mark proof acceptance blocked for the run.
2. Do not accept proof, disproof, differential, or release-decision artifacts
   generated on that host.
3. Install or repair the missing required dependency.
4. Rerun the probe from a clean shell.
5. Only resume proof generation after the probe passes all required checks.

Optional capability gaps:

- A missing optional solver does not block the whole release by itself.
- It does block any claim that depends on that solver's evidence.
- The proof receipt must identify the omitted capability and the resulting
  coverage reduction.
- Do not reinterpret an optional gap as coverage success because another solver
  passed a different class of check.

Examples:

- Required Z3 missing: block proof acceptance until `z3 --version` passes and
  the probe reports Z3 available.
- Required CVC5 missing: block differential SMT acceptance until
  `cvc5 --version` passes and the probe reports CVC5 available.
- Optional Lean missing: continue only if the release gate does not require
  Lean evidence; omit Lean-checked proof claims.
- Optional Apalache missing: continue only if temporal/state-machine model
  checking is not required for the task; record the gap.
- Optional Tamarin or ProVerif missing: continue only if symbolic protocol
  verification is not required; record the gap and omit those protocol claims.

## Troubleshooting

Z3 or CVC5 executable missing:

```bash
command -v z3 cvc5 || true
echo "$Z3_EXE"
echo "$CVC5_EXE"
```

`lean`, `lake`, `coqc`, `coqtop`, `apalache-mc`, `tamarin-prover`, or
`proverif` not found:

```bash
echo "$PATH"
command -v lean lake coqc coqtop apalache-mc tamarin-prover proverif || true
```

Add the relevant user-local binary directory to `PATH`, reinstall the missing
tool, then rerun the probe.

TypeScript compiler missing:

```bash
npm install -g typescript
tsc --version
```

Probe passes locally but fails in CI:

- Compare `python --version`, `which python`, `env | sort`, and `PATH`.
- Confirm CI activates the same virtualenv before running the probe.
- Confirm user-local binary directories are present in non-interactive shells.
- Confirm optional lazy-install variables are not masking missing required
  dependencies in developer shells.

## Acceptance Rule

A production proof run is acceptable only when the probe passes every required
dependency check on the host that generated the proof artifacts. Optional gaps
are allowed only when the current task and release gate do not require that
capability, and the resulting evidence packet clearly excludes those claims.
