# Frozen CodebaseIR scan policy

`codebase_scan_policy.py` adds the opt-in
`codebase-single-root-python-structural@1` profile over the existing native
`RepositoryCodebaseIndex`. It owns a derived immutable policy receipt, not a
second source head. Existing preparation entrypoints and checkpoint producers
are unchanged.

The admitted population is one committed Git root: tracked entries and Git's
standard untracked population, minus the explicitly pinned default/custom
exclusions. Dirty, staged, untracked and deleted entries retain the native
snapshot's exact byte, index and disposition identities. A subtree argument
cannot silently expand to the parent repository. Filesystem/unborn roots are
outside this selected profile.

Every admitted entry remains in the structural inventory. Python/pytest files
have the actual parser result and conservative static index; other UTF-8 files
have captured bytes without a Python AST. Failed parses, undecodable/oversized
files, symlinks and other opaque boundaries remain explicit. Real submodules
and nested repositories remain opaque nonregular boundaries: their contents
are not captured, traversed, trained or proved. The receipt does not infer that
an unknown boundary contains no relevant source.

Optional training/proof path selections reference successfully parsed captured
Python units. They never reduce the inventory denominator, supply correctness
labels, admit training or establish proof eligibility. Each selection has its
own count. The capability matrix explicitly distinguishes structural extraction,
source semantics, target execution, model work and proof authority.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import (
    CodebaseScanPolicy, prepare_policy_current, load_policy_receipt,
)

observation = prepare_policy_current(
    index, repository,
    repository_id="project:working-view",
    operation_id="capture:1", expected_head=None,
    policy=CodebaseScanPolicy(exclusions=("local-artifacts",)),
    training_paths=("module.py",), proof_paths=(),
    scheduler=scheduler,
)
receipt = load_policy_receipt(index, observation["receipt_cid"])
assert receipt["source_observed_live"] is False
```

Preparation uses native capture/publication, validates its complete source and
AST artifacts, seals the policy receipt, and observes the current source again.
The returned observation is point-in-time; it does not lock the checkout.
Historical receipt replay reconstructs native publication history and exact CAS
bodies in a fresh process, without scanning or executing the current target.
Changed or missing artifacts and resealed capability/inventory/selection/head
claims fail validation.

## Ignore rules and bounds

Repository `.gitignore` files that affect admitted directories must themselves
be included in the captured inventory. A self-ignored untracked rule file or a
custom exclusion that hides such a file is refused. Tracked source remains in
scope even when its name matches a Git ignore pattern. Rule changes alter the
captured identity.

Configured/default global ignore files and repository `info/exclude` must have
no active patterns in this first profile. Their exact bounded bytes, presence,
paths and configuration selectors are retained and checked before and after
preparation. Configuration drift or changed inactive bytes also refuses the
observation. Nonregular files are refused without blocking on FIFOs. Supporting
explicit declared external patterns is future work. Existing benchmark setups
with an active `.runtime` rule in `info/exclude` cannot use this profile unchanged;
this is not a replacement for their current preparation entrypoint.

The policy caps inventory at 256 entries and each captured source at 64 KiB.
Added Git scope queries run through the existing bounded native process owner
with 64 KiB output, 10-second CPU/wall and 256 MiB process limits. External ignore
file reads are bounded before reading. Existing source operations retain their
shared admission and cancellation controls. Their deadlines apply per owner
operation; this wrapper does not claim an overall RPI-022 deadline or hard
whole-owner memory limit.

`test_codebase_scan_policy.py` exercises the native Git/SQL/CAS route, actual
clean/dirty/changed-gitlink submodules, nonexecuting extraction, exact UTF-8/CRLF
bytes, independent selections, exclusions, unchanged-HEAD overlays, source and
configuration races, bounded metadata capture and independent-process replay.
The frozen RPI-001 scope is a qualified bounded profile; large-repository paging,
semantic/proof admission, DuckLake publication and default activation belong to
other acceptance criteria.
