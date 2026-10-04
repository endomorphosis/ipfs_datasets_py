# Capability-specific release sequence and pinned preflight

Release capture, conditional proof indexing, Intent grounding and model reuse
through separate qualified packages. The [release sequence](release_sequence.json)
names their dependency order and acceptance gates. The
[pinned manifest](release_bundle_manifest.json) binds 270 declared files,
twelve cell inventories and twenty-eight associations to twenty-six original
model/vector/descriptor assets. The [capture handoff](capture_handoff.md) and
[full pilot](pilot_spec.json) retain their existing runtime requirements.

The new [standalone preflight checker](../../../../scripts/ops/autoencoder/audit_ir_release_bundle.py)
reads explicit regular files and approved inventory pointers. It requires a
caller-trusted manifest SHA256, rejects changed/missing references, and supports
candidate-copy root relocation while retaining original source provenance.
It never imports runtime/model owners or runs Git, databases, solvers, training,
source functions or repository scans. Its output grants no runtime readiness,
task qualification, training, promotion, proof or effects.

## Measured preflight result

The [saved report](../../../../../../artifacts/codebase-ir-release-bundle-preflight-20261002/preflight-report.json)
records 269 matching files out of 270. All twelve inventories and twenty-eight
asset associations match, including all twenty-six original asset receipts.
The proof capability rejects one dependency: `logic/backends/process.py` differs
from the earlier expected pin. Its expected receipt is retained. The
[inspection](../../../../../../artifacts/codebase-ir-release-bundle-preflight-20261002/inspection.json)
records the observed drift separately; it does not replace the expected bytes.

Two Codebase384 checkpoint references used an archive's `_current` directory
alias. Their declared read locators now identify the physical archived files,
with exactly the same SHA256/byte receipts. The inventory's original path and
ownership remain unchanged. The checker rejects symlinks in relative locators;
it does not follow paths found inside a checkpoint or inventory.

Forty declared capture receipts, twenty-nine grounding receipts and all 158
model-reuse receipts match. Seventy-nine of eighty conditional-proof receipts
match. These groups overlap on shared foundations. None represents a complete
qualified dependency closure. Asset consistency is separate from teacher,
source-input, decoder or reconstruction qualification.

## Run the receipt check

From the datasets repository, use the reviewed manifest anchor below. A later
release must supply its expected hash through a trusted reviewed manifest or
verification record; computing a new hash of edited inputs does not approve
their changes.

```bash
python -B scripts/ops/autoencoder/audit_ir_release_bundle.py \
  --manifest docs/autoencoders/pilots/intent_codebase_grounding/release_bundle_manifest.json \
  --expected-sha256 a0dc5a98ed414a4ec0e2228bb1d14869a69197f6010077356764706cf4a23deb
```

Exit `0` means all declared receipt and inventory associations match. Exit `2`
means one or more declared references fail, which is the current expected
result. Exit `1` rejects the manifest, trust anchor or input declaration. The
checker writes JSON to stdout; it creates no databases or model artifacts.

Optional `--root-overrides` accepts a JSON object mapping declared root IDs to
absolute candidate-copy roots. The same source/asset bytes must verify at those
locators. Original source paths remain provenance and are never used as a
fallback when a relocated file is missing. Reads are bounded by a 2 MiB manifest,
512 declared files, 64 MiB per file and 256 MiB aggregate declared read budget.
Directory and file descriptors use POSIX no-follow traversal, so swapping a
parent for a symlink cannot redirect the read. File identity is rechecked around
reads. These are read bounds, not operation time or process RSS guarantees.

## Integrate packages in dependency order

| Package | Required result | Prerequisites |
| --- | --- | --- |
| P00 | Review and integrate the preflight tool/manifest; retain failures as evidence | None |
| P01 | Acquire a clean capture implementation with qualified package/import/producer closure | P00 |
| P02 | Implement and qualify B00/B01 registration, strict source guards, lease/deadline and operation recovery | P01 |
| P02S | Qualify selected-cell family/task contracts, isolated stores and typed routing | P02 |
| P03 | Qualify native semantics/frozen bounded evaluation, then conditional checker, cache, applicability and evidence index | P02, P02S |
| P04 | Select a complete supervisor lineage and qualify typed Intent/Codebase grounding | P03, P02S |
| P05 | Acquire original decoder/vector assets and integrate the GTE implementation bundle | P00 |
| P06 | Qualify input profiles, frozen model evaluation and decoder/inverse gates before private adaptation/distillation and span qualification | P03, P05, P02S |
| P07 | Qualify versioned cell delivery destinations; model promotion retains separate task gates | P04, P05, P02S |
| P08 | Integrate accepted capabilities in owning repositories and propagate reviewed parent gitlinks | P02 for capture; each additional selected package must pass its own gate |

P05/P06 do not delay deterministic capture. Each of the four IR families keeps
separate 8D/384D/768D heads, task/input/output/span profiles, decoders and
promotion decisions. P08 is scoped to the capabilities selected for that
release, rather than a declaration that every model lane is qualified.
P02S satisfies the selected C15 store/routing gate before C05 proof storage,
C17 typed joins or C08 adaptation. P05 is byte acquisition and does not complete
the C03 input-profile or C13 decoder gate. Work-item references describe scoped
deliverables; no package here marks a complete work item or full C11 rollout
achieved. Other IR-family training remains subject to its own cell gates.

## Close the actual integration gaps

The dated local datasets `origin/main` observation is
`d71ef66bee3b99777ed2d03d1bcd9ffd24b48ea1`; the inspected release checkout is still
`ace690e14442ba0ec45b886a660a2aa0fb3d186c`. The original 107 GTE additions remain
absent at the observed datasets ref. Several capture owners are already
released, while the conditional verifier/property-cache/evidence closure still
contains local-only files and divergent foundations. Git status in the older
active checkout alone cannot classify publication.

The expanded source seeds include twenty-one capture dependencies and
twenty-six additional proof dependencies. Package initializers matter:
`semantic_index/__init__.py` imports its facade and invalidation helpers;
`common/__init__.py` imports helper modules. Producer identities also read
installed `.py` files, including batch/workers for single-contract checks.
Bytecode-only packaging cannot satisfy those reviewed source receipts.

These are static dependency seeds. Direct/lazy imports, optional exports,
injected frontends, external executable/library origins and namespace-package
resolution still need runtime qualification in the isolated selected release.
The checker deliberately does not import owners to discover them. Native DuckDB,
lazy `multiformats`, Git/Linux process facilities, Z3/CVC5 launchers and optional
telemetry/fallback dependencies remain separately unqualified.

The current integer pipeline defaults to attempting supervisor AST evidence and
can fall back after an import exception. Do not assume it is supervisor-free.
Qualify the selected supervisor origin, or review a separately versioned
native-only profile. Resolve the changed process backend through reviewed
source/profile qualification and a new versioned release manifest; preserve
this manifest and its old receipt as history.

## Preserve decoder and storage ownership

All thirteen inventory documents retain their original bytes and associations.
The authentic source8 donor still needs cohort/basis migration; its 53-feature
input is distinct from its 8D latent. Source384 retains its existing explicit
Codebase envelope/Security-payload adapter and narrow two-operand task scope.
Legal768 remains an inherited initialization, and the other native768 heads
remain unavailable. None is relabeled as a qualified Codebase text decoder.

Reuse cached384 rows with their original source/target/split/vector profiles.
The prior transfer inventory contains no Codebase rows. Acquire missing native
inputs explicitly in a later versioned profile; never pad384 vectors to768 or
replace old assets. Distillation qualification must distinguish compiler-derived
donors, parser-assisted heads and independent source-conditioned teachers.
Legal text reconstruction and exact IR reconstruction remain separate metrics.

The proposed twelve registry/index/lake paths and Hub repositories stay
independently maintained. This preflight creates no runtime store or Hub
repository and performs no model promotion.

## Keep repository ownership explicit

The datasets supervisor gitlink remains `5306d49957bba7444a31639584e26378f3e3fb19`.
All thirteen nested owner source pins match that commit when read through the
sibling object store; its missing object in the nested clone is a separate
acquisition issue. The sibling planner/compiler/proof-scope lineage differs on
three files. Select a whole reviewed lineage rather than copying individual
files between checkouts.

Integrate reviewed source changes in their owning datasets or supervisor
repository, qualify clean acquisition and artifacts, then propagate the nested
gitlink and outer workspace pointers. Current workspace HEADs, local remote
refs and Git object availability are distinct observations. No fetch, branch
merge, push, gitlink update or remote publication occurred in this stage.
