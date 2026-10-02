# CodebaseIR semantic manifest

`codebase_semantic_manifest.py` implements `codebase-ir-manifest@1` over an
immutable native scan-policy receipt and structural source publication. The
selected semantic profile is the existing `python-integer-offset@1` compiler.
Every admitted inventory entry has a row, including opaque boundaries,
unsupported languages/parses/source effects and missing contracts.

This module supplies the whole-inventory envelope and joins existing owners:
`ProgramIR`, `ProgramContract`, source correspondences, effects/control-flow,
verification conditions and the exact SMT compilation. It does not introduce a
second program logic or a latent-vector predicate language. The original
unreleased `codebase_ir_targets.py` describes per-unit feature targets over the
generic adapter, and `codebase_verification.py`/`codebase_applicability.py` own
broader conditional execution/domain records. Those are separate interfaces;
this bounded envelope reuses the already qualified integer compiler rather than
copying their lowering or advertising their wider profiles.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import (
    build_codebase_semantic_manifest, load_codebase_semantic_manifest,
)

prepared = build_codebase_semantic_manifest(
    index,
    policy_receipt_cid=policy_observation["receipt_cid"],
    contracts=(IntegerOffsetContract("counter.py", "increment", "n", 1),),
)
manifest = load_codebase_semantic_manifest(index, prepared["manifest_cid"])
```

Contracts are explicit owner-supplied specifications, not established truths or
training labels. One exact `IntegerOffsetContract` can be selected per unit,
with at most 32 declarations. Unsupported declarations remain recorded beside
their unresolved region; they do not disappear from coverage. The profile admits
one annotated integer argument and one direct integer-offset return. Its native
runtime assumptions, including exact built-in integer inputs and excluded
resource exhaustion/module rebinding, remain explicit. Other effects, branches,
calls or language semantics require a separately qualified profile.

Logical unit IDs bind repository view and raw path. Native symbol IDs retain the
existing language/path/qualified-name/kind/namespace identity. Exact version CIDs
bind the complete source entry and native artifact references. A literal edit
keeps logical identity while changing exact versions; a path or qualified-name
rename creates a new logical identity without inferred equivalence. Structural
edge references remain available, but only the admitted local expression has a
closed dependency scope under its assumptions. No whole-program dependency
closure is claimed.

Each accepted unit references separately retained native program, contracts,
source correspondence, effects/CFG, VC set and compilation bodies. Historical
loading reconstructs these from exact captured source, checks every body and
reconstructs the complete manifest. It performs no live scan, target execution,
solver call, model fitting or CAS mutation. Missing bodies, changed source/model
joins, forged coverage, altered stable/exact IDs, omitted units and extra latent
predicate fields fail validation. Native file-backed source publication history
and independent-process replay remain required.

Optional evidence references accept only closed `conditional_smt_record` inputs
with exact immutable artifact CIDs, source/contract/compilation/query joins and
native authority flags. They are labeled **untrusted execution-record references**.
Binding integrity does not establish physical execution or checked-proof reuse.
The checked-evidence list and checked-property denominator remain empty/zero;
a forged kernel/behavioral authority flag is refused. Actual execution receipt
admission and proof-cache eligibility belong to their existing owners.

Coverage reports the complete inventory, structural outcomes, selected
contracts, source-bound models, unmodeled contracts/units, formalized properties
and declared/checked evidence separately. Selections cannot shrink the inventory.
The envelope permits at most 64 evidence references, 2 MiB per native semantic
artifact and 4 MiB per manifest; captured source retains the scan policy's bounds.
The selected scan policy is opt-in and rejects active ambient ignore patterns.
It does not activate this semantic envelope in default supervisor preparation,
train an autoencoder, claim a security proof or report benchmark performance.
