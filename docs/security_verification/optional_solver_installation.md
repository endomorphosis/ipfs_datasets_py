# Optional Solver Installation And Probe Plan

Task: `PORTAL-CXTP-086`

The solver planner is `scripts/ops/security_verification/install_optional_theorem_solvers.py`. It emits `security_ir_artifacts/environment/optional-solver-install-report.json`.

## Policy

The script runs in `plan_only` mode. It probes local executables and records install commands, but it does not install packages or mutate the machine.

Missing optional solvers do not block the required Z3/CVC5 path. They do block their own proof lanes with `blocked_optional_lane` or `degraded_optional_lane`, and reports from those lanes must not be accepted until the required tools are present and lane-specific validation passes.

## Solver Lanes

### Apalache

Purpose: TLA model checking.

Probe executables: `apalache-mc`, `apalache`.

Install plan examples:

```bash
cs install apalache
nix profile install nixpkgs#apalache
docker pull ghcr.io/apalache-mc/apalache:latest
```

### Tamarin

Purpose: protocol model checking.

Probe executable: `tamarin-prover`.

Install plan examples:

```bash
nix profile install nixpkgs#tamarin-prover
stack install tamarin-prover
```

### ProVerif

Purpose: symbolic protocol verification.

Probe executable: `proverif`.

Install plan examples:

```bash
opam install proverif
nix profile install nixpkgs#proverif
```

### Lean

Purpose: Lean proof-consumer kernel.

Probe executables: `lean`, `lake`.

Install plan examples:

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
elan default stable
```

### Coq

Purpose: Coq proof-kernel cross-check.

Probe executable: `coqc`.

Install plan examples:

```bash
opam install coq
nix profile install nixpkgs#coq
sudo apt-get install coq
```

## Validation

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py -q
PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --out security_ir_artifacts/environment/optional-solver-install-report.json
```

The report must include every optional lane and must classify unavailable lanes explicitly instead of silently treating them as proof-capable.
