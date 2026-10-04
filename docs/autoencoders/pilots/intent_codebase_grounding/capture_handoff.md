# B00/B01 integration and source-capture handoff

Implement the first capture adapter by composing the existing native owners.
Before running it, admit a specific implementation release, an isolated fixture,
its source policy and its durable owners. The [handoff contract](capture_handoff.json)
and [closed planning schema](capture_handoff.schema.json) define seven gates,
eight steps and eighteen additional capture/recovery cases. They refine B00/B01
and A01 in the [adapter plan](adapter_contracts.json); the existing
[pilot specification](pilot_spec.json) remains unchanged.

This is an implementation handoff. Registration, strict source guards, operation
journaling and measured acceptance are proposed adapters. No adapter, capture,
database, checker or training run was executed by authoring these documents.
Actual runtime bindings and case outcomes remain null.

## Select one implementation release

The [inspection record](../../../../../../artifacts/codebase-ir-capture-handoff-20261002/inspection.json)
binds source bytes, API signatures and local Git observations. The observed
datasets `origin/main` ref and release checkout point to `ace690e14442ba0ec45b886a660a2aa0fb3d186c`.
Several native capture owners and the scan-policy wrappers now match that
release. The active checkout remains at an older HEAD; a modified/untracked
file there can still byte-match a released Git blob. Classify the actual blob
comparison rather than using local status as an unpublished-code test.

The integer verifier, property cache, batch/workers, applicability and evidence
owners still include local-only dependencies. The verifier's implementation
identity reads batch/worker source files even for a single-check binding.
Several foundations also differ from released bytes. The inspected pins are
seeds for a capability-specific dependency closure, not proof of complete
installation or a clean-checkout reproduction.

For supervisor integration, the thirteen nested owner pins match the datasets
gitlink commit's source bytes when read through the sibling Git object store.
That commit object is missing from the nested clone. Distinguish missing objects
from missing APIs. The sibling planner, formal compiler and proof-scope index
have different bytes; select and review a complete lineage before downstream
grounding. These are local ref observations; no remote fetch was performed.

Capture readiness, conditional-check readiness, grounding readiness and model
readiness are separate results. Only the capture capability is required for B01.
Do not import local-only proof/model modules merely to register a source view.
The future executable gate must bind actual package origins, direct/lazy imports,
package initializers, producer identity closures and dependency/executable
versions to the selected release.

## Bind the fixture and owners

Acquire the parent operation lease and outer deadline before capability/package
metadata checks, durable owner construction, fixture materialization and Git
inspection. Carry that lease and the remaining budget through every setup and
capture stage; the later stages do not acquire it for the first time.

Use the exact authored H0 `counter.py` buffer from the pilot specification in a
new isolated committed Git repository. Assign an explicit repository-view ID.
There is no existing `index.register` method: registration belongs to the
proposed outer adapter. The fixture root, Git commit, registration and operation
IDs must be measured at execution time.

Place the source database, CAS, scheduler state, journals, run manifests and
logs outside that root. Bind one exact native file-backed `DuckDBASTStore`, its
`DuckDBASTIngestor`, an `ImmutableCAS` and `CodebaseCatalog` to the index. The
catalog and ingestor must share the same store/connection and artifact objects.
Serialize writes through the owner; workers exchange artifacts and head tokens,
not inherited DuckDB connections. Catalog construction can create SQL tables.

The canonical source owner captures once for all relevant cells. It remains
separate from the twelve model registry/index/lake namespaces. Existing cell
inventory receipts, checkpoint bytes and cached vectors are retained.

## Enforce source policy explicitly

The native `prepare_current` API accepts dirty and other snapshot modes.
Snapshot ingestion bypasses the ordinary ingestor dirty-tree policy.
`CodebaseScanPolicy` enforces an exact committed Git root but admits both
`git-clean` and `git-working`. Native `git-clean` ignores excluded dirty paths;
it is not a root-wide cleanliness assertion.

For H0, require `git-clean` plus a separately reviewed empty root-wide Git
status measurement covering tracked/index and nonignored untracked paths,
without filtering declared exclusions. Standard ignored files remain outside
that status claim. Bind built-in/custom exclusions and exact repository ignore
rules through the native policy receipt; reject active external ignore patterns
under the frozen profile.

Fence the guard before capture, after publication before outer acceptance and
at current use. An edit between fences can leave a complete native structural
head while causing outer admission to fail. Preventing any dirty native
publication would require an additional reviewed publication hook; the current
wrapper does not provide that strict-clean hook. For a later H1, either commit
the successor before strict-clean capture or admit a separate overlay profile.

Keep the full nonexcluded population within 256 entries and 65,536 bytes per
file. Proof selection `counter.py` does not narrow the inventory; initial
training selection is empty. Oversized/opaque, partial, failed and unindexed
entries stay accounted for. Only successfully parsed Python candidates are
selectable; selection alone admits neither training nor proof.

## Compose the existing calls

The outer adapter performs setup and capture under one acquired operation
lease/deadline:

1. Acquire the parent operation lease and outer deadline before any setup or
   metadata checks. Admit the implementation, construct owners and materialize
   the fixture under that budget. Retain the original complete expected head
   and separate outer/native operation IDs. The outer request binds registration,
   policy, implementation/owner identity, selections and resource contract.
2. Call `prepare_policy_current` with the injected index, exact root/view,
   operation ID, original expected head, `CodebaseScanPolicy`, empty training
   selection and `counter.py` proof selection. Pass the parent lease,
   cancellation signal and remaining time.
3. Reconcile native publication and policy sealing separately. The wrapper
   captures and publishes, reobserves, seals a policy receipt, then refences
   source and ignore scope. Its successful return contains serialized `head`
   and `receipt_cid`; its point-in-time observation is not a future edit lock.
4. Decode the actual head using `CodebaseHead.from_dict`. Authenticate history
   with `load_policy_receipt`. Recompute native identities and complete coverage
   under compatible producer pins.
5. Establish current source and ignore applicability with `verify_policy_current`.
   Apply the separate strict guard and remaining-budget gate. `current()` alone
   reads the durable head; it does not inspect source. Native
   `CodebaseObservation` has `head` and `manifest`, with no native observation CID.
6. Create a new immutable measured outer handoff only after acceptance. Any
   observation wrapper needs its own reviewed schema/identity owner. Reobserve
   source and policy before downstream consumption.

The JSON carries exact API signatures extracted from the inspected source.
Historical policy loading and operation resolution authenticate stored records;
they grant no currentness, behavioral proof, model qualification or effects.

## Recover failures and declare resource limits

The native request binds repository ID, derived manifest CID and original
expected head. Preserve its exact identity before an ambiguous commit through
a reviewed journal hook or owner recovery extension. The public capture wrapper
does not currently expose that prepublication hook. If a lost response leaves
the request CID unknown, return `recovery_pending`; do not retry with today's
head or guess a request identity.

Track native commit, policy seal, current observation and response delivery as
distinct stages. Policy failure does not roll back a previously complete native
head. Recover an exact operation through `resolve_operation` only with its
authenticated request identity. A returned receipt may be historical; an exact
retry cannot reactivate old ASTs or old-generation authority.

Native Git snapshot calls currently materialize metadata without output/RSS
caps, and check entry counts afterward. Bounded scan-policy helper queries do
not bound all native Git acquisition. The wrapper also reuses time limits per
subcall. Declare these cooperative limits honestly. Before whole-repository
admission, implement reviewed bounded native metadata acquisition and remaining
deadline propagation. The isolated fixture needs its own measured metadata
gate; no operation-wide hard timeout or RSS bound is established here.

## Accept capture independently of decoder readiness

Retain the source8 checkpoint as an authentic donor with cohort/basis migration
required. The single-argument offset remains unsupported for the source384
two-operand task, and no native Codebase768 head is asserted. Those lane results
do not block deterministic capture. Other family inventories retain their own
identities; do not relabel their weights or replace learned components randomly.

B01 acceptance requires actual native publication, complete population
accounting, an authenticated policy receipt and fresh source/policy applicability
under the selected implementation and owner identities. The eighteen K cases
test capture, recovery and readiness; the twenty-three G cases remain the later
full pilot specification. All expected outcomes are currently unexecuted.
