# Optional Solver Installation And Verification

Task: `PORTAL-CXTP-086`

The solver entry point is
`scripts/ops/security_verification/install_optional_theorem_solvers.py`. It
emits `security_ir_artifacts/environment/optional-solver-install-report.json`.
It manages Z3, CVC5, Apalache, Maude, Tamarin, ProVerif, Lean, Rocq,
SymbolicAI, and ErgoAI. It also reports Leanstral as an advisory proof-assistant
lane; Leanstral is not a local proof-kernel binary and is never treated as
proof authority.

## Read-Only Default

Without an installation flag, the script is `plan_only`: it probes executable
and Python-binding availability, records managed-version drift, and writes a
safe command for each installable lane. It does not download, build, update,
or invoke `sudo`.

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --out security_ir_artifacts/environment/optional-solver-install-report.json
```

Missing, partially installed, or version-drifted solvers are classified as
`blocked_optional_lane` or `degraded_optional_lane`. They cannot be used as
proof evidence until the corresponding lane validates its model and runtime.
Leanstral remains `degraded_optional_lane` until an approved Leanstral route or
local weights are configured and the Lean/Lake kernel lane is independently
ready.

## Managed Installation

Install only the needed lanes. Every stage is printed with an
`[ipfs_datasets_py]` prefix and retained in the report, so a UI can distinguish
a download, extraction, OPAM switch build, source build, or validation from a
stalled program.

```bash
# Tamarin downloads the pinned checker and Maude, then asks Tamarin to validate the pair.
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --install --yes --solver tamarin

# ProVerif builds the pinned headless source. It reuses OCaml when present or
# creates an isolated OPAM switch under the user-local solver root.
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --install --yes --solver proverif

# Rocq is installed as the reviewed 9.1.1 kernel in an isolated OPAM switch.
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --install --yes --solver rocq
```

If OPAM is missing, the Rocq or ProVerif path remains non-mutating unless the
operator explicitly permits a package-manager bootstrap:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --install --yes --allow-sudo --solver rocq --solver proverif
```

The installer never uses interactive `sudo` without `--allow-sudo`. When a
platform does not have a reviewed artifact or bootstrap recipe, set a
non-interactive solver-specific command such as
`IPFS_DATASETS_PY_TAMARIN_INSTALL_COMMAND` or
`IPFS_DATASETS_PY_PROVERIF_INSTALL_COMMAND`.

Leanstral has no `--install` command in this path. Configure it with an
approved model route such as `IPFS_DATASETS_PY_LEANSTRAL_MODEL=labs-leanstral-2603`
or a reviewed local weights path in `IPFS_DATASETS_PY_LEANSTRAL_WEIGHTS`, then
compile every generated candidate through Lean/Lake before accepting evidence.
The report records this as `advisory_lane.proof_authority=false`.

## Reviewed Updates

Updates are operator-triggered, not a background latest channel. They refresh
only the selected lane to the reviewed version, URL, and checksum defined in
`prover_installer.py`.

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/install_optional_theorem_solvers.py \
  --update --yes --solver tamarin --solver proverif --solver rocq
```

Use `ipfs-datasets-install-provers --check-updates` to inspect drift without
changing the host. A version mismatch remains a coverage gap; it is not an
automatic reason to accept a proof produced by a different solver release.
Advisory Leanstral route changes are manual-review events, not silent updates.

## Validation

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_optional_solver_installer.py \
  tests/unit_tests/logic/external_provers/test_lazy_native_solver_installation.py -q

PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/probe_tamarin_runtime.py \
  --out security_ir_artifacts/environment/tamarin-runtime-report.json
```

The Tamarin runtime probe is required because `tamarin-prover` and `maude`
being on `PATH` alone does not prove that the pinned pair is usable. ProVerif
and Rocq reports must likewise retain their executable versions and successful
model or kernel checks before they are used in a security claim.
