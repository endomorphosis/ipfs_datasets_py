# Lazy Theorem-Prover Installation

The Xaman and crypto-exchange verification lanes keep solver dependencies
optional. Importing `ipfs_datasets_py.logic.external_provers` never downloads a
solver. A native solver is resolved only when a caller starts an actual model
check, protocol proof, SMT-LIB run, or proof-kernel compilation.

## Python Extras

Install the optional Python bindings when SMT bridges will be used:

```bash
pip install -e '.[theorem-provers]'
# or
pip install -r requirements-theorem-provers.txt
```

This extra installs `z3-solver`, `cvc5`, and `symbolicai` (imported as
`symai`). It does not install native solver executables during `pip install`.

## Native Solver Behavior

On first execution, `ensure_prover_executable` looks on `PATH` and in the
user-local solver root. If the executable is still missing, it emits visible
status messages and installs the solver into:

```text
~/.local/share/ipfs_datasets_py/theorem-provers
```

Set `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` to use another writable location.
The installer creates launchers in that root's `bin/` directory and adds it to
the current process `PATH`.

| Solver | First-use installation |
| --- | --- |
| Apalache | Pinned portable JVM release; requires Java and works on Linux x86_64/arm64. |
| Maude | Pinned, checksum-verified native release; Linux arm64 uses the reviewed Debian Maude `3.5.1` package. |
| Tamarin | Pinned native release when available, or a managed Stack source build on Linux arm64; paired with an explicitly compatible Maude. |
| ProVerif | Pinned source archive, checksum verified, built without the optional GTK UI; reuses OCaml or creates an isolated OPAM switch. |
| CVC5 CLI | Pinned, checksum-verified static release for Linux/macOS x86_64 and arm64. |
| SymbolicAI (`symai`) | Optional Python package installed from the theorem-provers extra or on requested bridge use. |
| Lean | Official `elan` bootstrapper in the user's home directory, using the reviewed `v4.31.0` toolchain unless overridden. |
| Coq/Rocq | An isolated OPAM root and switch under the user-local solver root; installs and version-verifies Rocq `9.1.1` and provides Coq-compatible launchers. |
| Isabelle | Official checksum-verified Isabelle bundle for Linux x86_64 or arm64. |
| Vampire | Pinned checksum-verified native release for Linux x86_64 or arm64. |
| E | Pinned checksum-verified source release built user-locally. |
| ErgoAI | Reviewed ErgoAI distribution used as the native F-logic authority. |
| Z3 | The optional `z3-solver` Python binding used by the exchange runner. |

For unsupported platforms or organization-managed packages, provide a
non-interactive custom command before starting the proof:

```bash
export IPFS_DATASETS_PY_APALACHE_INSTALL_COMMAND='...'
export IPFS_DATASETS_PY_TAMARIN_INSTALL_COMMAND='...'
export IPFS_DATASETS_PY_MAUDE_INSTALL_COMMAND='...'
export IPFS_DATASETS_PY_PROVERIF_INSTALL_COMMAND='...'
export IPFS_DATASETS_PY_CVC5_INSTALL_COMMAND='...'
export IPFS_DATASETS_PY_COQ_INSTALL_COMMAND='...'
```

The detailed progress stream is available to an interface through
`ProverInstallEvent`:

```python
from ipfs_datasets_py.logic.external_provers.lazy_installer import (
    ensure_prover_executable,
)

executable = ensure_prover_executable(
    "apalache",
    reason="Xaman Testnet invariant execution",
    progress=lambda event: ui.publish(event.phase, event.message),
)
```

The default terminal integration prints the same messages with the
`[ipfs_datasets_py]` prefix. Long-running downloads, extraction, OPAM switch
creation, and ProVerif builds each emit a distinct stage.

Tamarin installation is complete only after its pinned binary accepts the
selected Maude `3.5.1` runtime with Tamarin's `checking installation: OK`
marker. A present executable with an incompatible Maude runtime is reported as
a failed installation, not as a ready protocol solver.

## Managed Portfolios

The unified installer can bootstrap reviewed solver groups before a run:

```bash
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict
ipfs-datasets-install-provers --portfolio legal_ir_full --yes --strict
```

`legal_ir_generation` installs Z3, cvc5, Lean, Vampire, E, and ErgoAI for the
normal Leanstral/Hammer candidate path. `legal_ir_specialists` adds Apalache,
Maude, Tamarin, and ProVerif. `reconstruction` adds Rocq and Isabelle.
`legal_ir_full` is their complete union plus SymbolicAI.

Setup can select the same behavior non-interactively:

```bash
export IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS=1
export IPFS_DATASETS_PY_AUTO_INSTALL_ALL_PROVERS=1
export IPFS_DATASETS_PY_PROVER_INSTALL_STRICT=1
```

Alternatively, set
`IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIOS=legal_ir_generation,legal_ir_specialists`
to choose explicit groups. The supervised Leanstral worker preflights
`legal_ir_generation` by default to keep restarts bounded, while a missing
specialist is installed lazily when its route is first requested. Set
`LEANSTRAL_AUDIT_PROVER_PORTFOLIO=legal_ir_full` to require every managed
solver before the worker starts.

## Control and Safety

Set `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0` to block all automatic native
installation. Set `IPFS_DATASETS_PY_LAZY_INSTALL_STRICT=1` to surface an
installer failure as an exception. No installer uses `sudo` unless
`IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1` is explicitly set.

When OPAM is not present, the standalone installer can bootstrap it only after
the operator explicitly allows a package-manager operation:

```bash
ipfs-datasets-install-provers --yes --allow-sudo --coq --proverif
```

The runtime paths do not request `sudo` implicitly. They instead report a
blocked stage with the required preparation, so an interface can keep showing
progress and actionable state.

## Manual Updates

No solver is upgraded during import or normal execution. The package treats
solver versions as reviewed verification inputs. Check managed-version drift
without changing the machine:

```bash
ipfs-datasets-install-provers --check-updates
```

Refresh only a selected solver after reviewing the new version and its effect
on proof evidence:

```bash
ipfs-datasets-install-provers --update --yes --apalache
ipfs-datasets-install-provers --update --yes --tamarin
ipfs-datasets-install-provers --update --yes --maude
ipfs-datasets-install-provers --update --yes --proverif
ipfs-datasets-install-provers --update --yes --cvc5 --cvc5-cli
ipfs-datasets-install-provers --update --yes --z3
ipfs-datasets-install-provers --update --yes --lean
ipfs-datasets-install-provers --update --yes --coq
ipfs-datasets-install-provers --update --yes --symbolicai
ipfs-datasets-install-provers --update --yes --ergoai
```

`--update` refreshes to the managed, reviewed versions declared by the
installer, rather than silently tracking upstream latest. Updating a pinned
release requires a reviewed code change to its version, URL, checksum, and
solver evidence. Use `IPFS_DATASETS_PY_LEAN_TOOLCHAIN` to choose a reviewed
Lean toolchain and `IPFS_DATASETS_PY_ERGOAI_INSTALL_COMMAND` to select a
reviewed ErgoAI release for source or vendor-specific updates.

Leanstral is an optional model route for proposing Lean proof steps. It is not
a local theorem-prover binary and needs its own model credentials/weights; it
does not replace checking a generated proof with the installed Lean kernel.

Installing or finding a solver is environment evidence only. A proof result
still requires a reviewed model, pinned input artifacts, successful solver
output, and the assurance policy's independent evidence requirements.
