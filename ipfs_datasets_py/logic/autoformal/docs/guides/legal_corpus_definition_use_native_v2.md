# Conditional native execution for V2 definition use

The separate [native executor](../../legal_corpus_definition_use_native_v2.py)
builds the existing nine-file, six-module definition-use preparation and observes
three conditional Lean theorem checks. It preserves the original preparation,
assessment, review outcome and `build_eligible=false`. Its compilation receipt
records an engineering observation; it does not admit a statutory
interpretation, graph, proof cache entry, training example or unified corpus.

The original official V2 profile's qualification passed **109 focused tests**
and two authored native projects. These historical results do not qualify the
separate parent profile described below.
The implementation and its
[focused tests](../../../../../tests/unit/logic/autoformal/test_legal_corpus_definition_use_native_v2.py)
use the frozen resource-owned validation path. Synthetic process
results in unit tests are separate from the actual native theorem checks. The
[authored native driver](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/run_authored_native_definition_use.py)
compiled twelve modules and observed six conditional theorem checks using
fictional donor and consumer documents, unavailable trust, and zero supplied
reviews. The qualification scope is engineering behavior under explicit
hypotheses; all statutory review and admission gates remain open.

## Existing preparation remains authoritative for its inputs

Read the [definition-use guide](corpus_definition_use_v2.md),
[combined review guide](corpus_definition_use_review_v2.md) and
[conditional project preparation guide](legal_corpus_definition_use_lake_v2.md)
for their input contracts. This executor consumes the exact
`DefinitionUseCorpusPreparation` produced by
`legal_corpus_definition_use_lake_v2`. It does not implement another formula
parser, renderer, resolver, reviewer or proof engine.

The supported component has two distinct physical documents, one explicit unary
definition in each, a shared declared applicability, and an explicit assumed
alias. Both endpoints have the same family, currently FOL or TDFOL. The source
interpretations, complete joint AST, scoped definition lookup, registry
partitions, physical contexts, dependencies and combined review evidence retain
their existing public owners and replay checks. Same-document multiple
definitions, arbitrary normative uses, multiple donor mappings and cycles remain
outside that profile.

All nine generated inputs and all six modules are regenerated through the
existing public preparation validator before execution and again after the
native result. The original assessment is supplied as exact file bytes with its
independently expected raw SHA256. The caller must retain all original combined
review validation inputs, including the nested original source/use byte groups,
component, registry, query, lookup, observed pins and evidence bodies. Canonical
record hashes do not replace those original bytes.

A pending or rejected assessment can be a valid input for this explicit
engineering build when its original public validator replays it successfully.
An altered or outdated assessment that its original inputs no longer reproduce
does not pass that replay. A valid regenerated assessment can report stale
dependencies and retain those blockers during an engineering build. Native
success does not change the assessment or its prerequisites and never supplies absent trust,
reviews, source interpretation or applicability evidence. The receipt copies
the original intake binding, review status, blockers, selected-trust prerequisite
status, `build_eligible` and execution handoff without upgrading them.

The existing frozen preparation contains these nine files:

| Input | Purpose |
| --- | --- |
| `lakefile.toml` | Declares only the existing `legal` library target. |
| `lean-toolchain` | Binds an explicit versioned Lean toolchain. |
| `v2-input-bindings.json` | Binds the exact original assessment and combined review inputs. |
| `LegalCorpusV2/Prelude.lean` | Existing native family interpretation definitions. |
| Two `LegalCorpusV2/Definition<hash>.lean` files | Exact donor and consumer definitions. |
| `LegalCorpusV2/Alias<hash>.lean` | Explicit alias and the first conditional theorem. |
| `LegalCorpusV2/Joint<hash>.lean` | Original joint formula and two conditional theorems. |
| `LegalCorpusV2.lean` | Closed root import. |

The six expected modules are the prelude, donor, consumer, alias, joint and root.
The original manifest fixes their names, import graph, source hashes and theorem
names. A caller cannot repair a changed project's manifest and substitute it:
full regeneration must still reproduce every original byte.

## Stable API and independent commitments

Public import of the executor uses only the Python standard library. The
existing preparation and process owners are imported lazily after complete
caller-controlled preparation and review inputs are bounded. The original
preparation type is enforced after those bounds and before public regeneration.

The executor exports four functions:

```python
preparation_sha256(preparation)

validate_definition_use_native_v2(
    preparation, assessment_raw, *,
    expected_preparation_sha256, expected_assessment_file_sha256,
    review_inputs, toolchain,
)

build_definition_use_native_v2(
    preparation, assessment_raw, *,
    expected_preparation_sha256, expected_assessment_file_sha256,
    review_inputs, toolchain, lake_executable, output_directory,
    timeout_seconds=60, cancellation=None,
)

compilation_receipt_sha256(receipt)
```

`preparation_sha256` commits the full canonical ordinary JSON envelope
`{"manifest": <complete parsed original manifest>, "files": [[path, text], ...]}`.
The manifest includes its CID, and the file list contains all nine distinct
sorted generated files. Canonical serialization uses sorted keys, compact
separators, UTF8, and finite JSON values. This helper produces a commitment; it
does not establish that the preparation is valid. Validation compares it with
the independently expected frozen commitment and publicly regenerates the
complete preparation.

Keep these namespaces distinct:

- `expected_preparation_sha256`: full canonical manifest-and-files envelope.
- `expected_assessment_file_sha256`: exact original assessment file bytes.
- The assessment's internal commitment: owned by the existing review engine.
- `preparation_manifest_sha256` in the receipt: exact original manifest text
  bytes.
- `compilation_receipt_sha256`: full canonical separate observation receipt.

The caller acquires the established owned validation resources before invoking
the build and retains them until native cleanup and durable output disposition
are confirmed. The API does not acquire a replacement outer lease or provide a
resource-admission bypass. `output_directory` must be fresh; existing output is
never overwritten. Validation-only calls do not run a compiler.

## Three conditional checks and their assumptions

The qualified theorem names come from the unchanged preparation manifest. Their
short names and obligations are:

| Theorem | Hypotheses and conclusion |
| --- | --- |
| `consumer_predicate_iff_donor_body` | Assumes the original donor definition and explicit alias; proves the selected consumer body predicate is equivalent to the donor body. |
| `joint_of_components` | Assumes the exact donor definition, consumer definition and alias; assembles the original joint formula. |
| `joint_matches_original` | Checks the generated modular joint against the original native joint formula by definitional equivalence. |

The fragments share one supplied interpretation, entity carrier and natural
number evaluation time. The alias remains assumed and unproved as a fact. The
consumer definition is a separate premise for joint assembly. A donor body and
alias do not generally establish the consumer head for an arbitrary Boolean
consumer body.

Only a fully passed separate engineering receipt can set `proof_checked`,
`kernel_proofs_checked`, `conditional_proofs_verified` and
`lean_compilation_verified` to true. Its `conditional_kernel_status` then reads
`checked_under_explicit_hypotheses`. These flags concern only the exact generated
conditional obligations. `proof_authority`, source/legal/review authority,
meaning/admission, model execution, learned translation, training/gold and
source-to-model equivalence remain false. Training and evaluation-gold masks
remain integer zero.

The complete original assumption/status list is retained verbatim as
`original_preparation_theorem_assumptions`. The receipt's `theorem_assumptions`
preserves the actual hypotheses while omitting the preparation's obsolete
sentence saying that native checking has not run. Execution status belongs in
`conditional_kernel_status`. The original preparation itself is unchanged.

## Native result, source and lifecycle custody

The executor reuses the existing installed-toolchain owner to require an
explicit installed native Lake ELF, its sibling Lean ELF, matching version
probes and binary SHA256 pins. It invokes the shared bounded process runner with
this exact argument vector:

```text
<verified-native-lake> --offline --no-cache build legal
```

This first receipt schema conservatively retains the preparer's inherited
`toolchain_probed=false`, `installed_toolchain_verified=false` and
`native_build_profile_registered=false`, even when its separate
`version_probes`, `binary_sha256`, `binaries_unchanged` and native result record
actual successful execution. Those inherited flags do not count process calls
or deny the recorded version probes. Their top-level names are ambiguous for an
execution receipt: consumers must use the explicit observations and keep the
original preparation's handoff separate. A future versioned schema should place
inherited preparation flags under an explicit original-preparation namespace
and give actual installed-tool observations their own names. This guide does
not silently change the frozen schema or reinterpret those conservative false
values as new authority.

The expected outputs are all six nonempty `.olean` files and all nine executed
input files. Missing or extra outputs, empty artifacts, changed source bytes,
changed commands, unavailable runtimes, truncation, resource failure, compiler
failure or failed post-run replay prevent success. Binary and producer pins are
rechecked. Absolute producer paths retain the existing checkout-specific
portability boundary; these pins do not authenticate a software distribution or
its entire library closure.

The runner must return native runtime and a positive exact-integer PID. The
receipt requires the exact typed `NativeToolLifecycleObservation` with confirmed
leader reaping, sampled descendant/group cleanup, joined readers/writer and
workspace removal. It also checks a current-caller binding: the observation's
parent PID equals `os.getpid()`, parent birth ticks are a positive exact integer,
and the leader's parent PID matches. The leader owns its observed process group
and session. Every observed descendant must have the same process group and
session; an observed foreign group or session prevents
`observed_process_scope_passed` even if its cleanup later completes.

These are sampled ownership observations. They do not prove the absence of an
escape between samples or attest kernel containment. A normal clean exit can
have `process_tree_terminated=false`, because that field describes an
intervention, rather than a requirement to kill an already exited process.

All three exact qualified theorem names must each appear once in actual stdout
as Lean's quoted empty-axiom message:

```text
'<qualified theorem name>' does not depend on any axioms
```

An anchored `info: <exact generated theorem module .lean path>:line:column: `
prefix is allowed, including leading `./` segments in that path. Arbitrary
inline text, wrong source paths, duplicate results, unknown theorem names,
nonempty axiom reports and axiom claims appearing only in stderr cannot satisfy
the check. The receipt retains the observed dependency map and parser errors;
full bounded logs remain available separately.

If the bounded runner raises `OwnedToolCleanupError`, the executor attempts to
retain the frozen project and a failed cleanup observation, then re-raises the
same exception with its original cleanup handle. It never replaces that handle
with a serialized success flag. The caller retains its resource custody until
the original owner confirms cleanup. Preservation failure is attached as a
note and does not discard the original cleanup exception.

A private instance of the existing frozen preparation type captures the exact
invoked files. Post-run validation rechecks the caller's original object against
that snapshot. If it changes during execution, qualification fails and retained
project bytes still describe the original invocation.

## Bounds and retained observations

The complete original review tree and assessment share a 48-MiB preflight
budget. The assessment and sealed preparation manifest each retain a one-MiB
bound. Generated files total at most eight MiB; the full canonical preparation
envelope has a separate 20-MiB bound. Ordinary-container, UTF8, finite-number,
depth and node bounds apply before lazy owner imports. Existing source, review,
signature and evidence limits are preserved by their public validators.

One compiler invocation has a caller-selected timeout in `(0, 60]` seconds,
matching CPU limit, sampled two-GiB process-tree RSS guard, sampled 128-MiB
workspace limit, two-MiB capture bound and exactly fifteen declared outputs.
`LEAN_NUM_THREADS=1` and the explicit `ELAN_TOOLCHAIN` are set. These sampled
guards retain the shared runner's documented limits and do not become a
filesystem quota or kernel resource-containment guarantee.

A successful build retains 29 regular files:

| Location | Files |
| --- | --- |
| `project/` | Nine original generated inputs plus `corpus-manifest.json`. |
| `compiled/` | Six observed nonempty `.olean` files. |
| `executed-inputs/` | Nine exact input files collected from the actual workspace. |
| Build root | `stdout.txt`, `stderr.txt`, `runner-error.txt`, `build-receipt.json`. |

Operational failures retain whatever bounded declared artifacts and executed
inputs were returned, so their retained file count can be smaller. A failed
receipt never invents missing output evidence. Existing closed project and
artifact transports perform exact readback, reject unsafe entries and fsync
retained files/directories.

Complete bounded log text is retained in the three log files. Each receipt
preview covers at most 32 KiB of the UTF8 log bytes, with replacement decoding at
the boundary and NUL escaped for ordinary JSON. Malformed original process UTF8
can expand during replacement decoding; retained text is bounded to three times
the runner capture bound. The receipt records each full log's SHA256 and byte
length, identifies preview truncation, and remains bounded to one MiB.

## Qualification evidence

The [native baseline](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/baseline.json),
[initial owner design](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/owner-design.json)
and [parent-binding amendment](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/owner-design-parent-binding-amendment.json)
record the implementation boundary. The
[frozen focused-test request reference](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/test-request-reference.json)
identifies the independently pinned owner, tests, selected source files and
resource-owned check. The [test receipt](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/test-receipt.json)
records **109 passed, zero failures, errors or skips**, including synthetic
process-boundary controls. The
[authored driver](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/run_authored_native_definition_use.py)
and [independent readback script](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/read_authored_native_outputs.py)
performed the separately recorded native qualification and data-only readback.

Installed Lean 4.26.0 built both family projects, producing twelve nonempty
module artifacts and eighteen unchanged executed input readbacks. All six
conditional theorem instances emitted the required empty-axiom messages. Eleven
driver checks included two resealed pre-build refusal controls. Two build
commands and four native version probes ran in total; no negative native build
is counted in this phase. Both successful native-phase validation reservations
were durably released.

The [independent readback receipt](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/independent-authored-native-readback.json)
verified all 98 files (6,940,049 bytes), thirty producer sources, four fixture
sources, 906 sealed-record occurrences representing 273 unique CIDs, sixty
all-false authority objects, 36 strict integer-zero masks and 1,609 false
semantic fields. Each family retains thirteen physical contexts with 78 slots
and the same pending assessment. Recorded sampled lifecycle observations,
binary/source pins, logs, module coverage and conditional premises matched.
The readback imported no project owners and did not reexecute Lean.

The [qualification receipt](../../../../../../../artifacts/legal-ir-definition-use-native-20261015-01/qualification-receipt.json)
binds these results. The earlier integration's symlink case remains separately
unqualified; its interrupted selector attempt and full 250-MB retained claim
are recorded in the [integration guide](definition_use_v2_integration.md).

The qualified authored endpoints are fictional examples in FOL and TDFOL, with
unavailable trust and `reviews=[]`. They do not add a second actual statutory
source, supply a legal reviewer or close the actual sampled source's pending
population. Actual source-first interpretation, combined legal/formal review,
source-equivalence proofs, learned-model training and convergence, and any
unified corpus publication remain separate work.


## Literal-parent conditional native profile

The separately versioned parent profile extends this executor through three fixed entrypoints:

```python
validate_parent_definition_use_native_v1(
    preparation, assessment_raw, *,
    expected_preparation_sha256, expected_assessment_file_sha256,
    review_inputs, toolchain,
)

build_parent_definition_use_native_v1(
    preparation, assessment_raw, *,
    expected_preparation_sha256, expected_assessment_file_sha256,
    review_inputs, toolchain, lake_executable, output_directory,
    timeout_seconds=60, cancellation=None,
)

parent_compilation_receipt_sha256(receipt)
```

The existing `preparation_sha256` helper commits the complete parent preparation
with the same manifest-and-nine-files recipe. It does not validate the
preparation or select an execution profile. Both profiles use the exact existing
`DefinitionUseCorpusPreparation` class and fixed renderer layout. They retain
separate validation and receipt domains:

| Record | Parent domain |
| --- | --- |
| Original preparation | `legal-corpus-parent-definition-use-lake-preparation/v1` |
| Original preparation profile | `replayed-parent-definition-use-conditional-project/v1` |
| Native observation | `legal-corpus-parent-definition-use-native-build/v1` |
| Native observation profile | `replayed-parent-definition-use-conditional-native-build/v1` |

The parent validator delegates to
`legal_corpus_definition_use_lake_v2.validate_parent_definition_use_corpus_v1`.
That public owner regenerates the exact project from the original parent
combined-review assessment, both endpoint candidate/report/request byte groups,
physical-parent inputs, all declared contexts, original lookup population,
independent pins and current dependency observations. The native adapter also
requires the exact parent preparation schema and profile. Changing a schema,
relabeling official input, or supplying a recomputed manifest hash cannot replace
that replay. Public entrypoints have no profile-switch argument; their fixed
domain is chosen in code. The two receipt hash helpers each accept only their
own receipt schema and produce commitments, not proof or admission credentials.

The parent build uses the existing shared implementation: replay first, capture
the immutable original nine-file preparation, verify the explicitly installed
native Lake and sibling Lean, run the bounded offline build, and replay the
original parent preparation again after the result. The post-run replay includes
physical source custody, complete review context, lookup evidence and observed
artifact/policy pins. A changed original source, evidence group, interpretation,
project or producer prevents successful qualification. Both original ASTs and
the explicit alias remain retained without replacement.

The command, bounds and output obligations are unchanged: one build of target
`legal`, one Lean thread, six nonempty `.olean` outputs, nine exact executed input
readbacks, and three exact qualified empty-axiom observations. Actual invocation
through the installed-toolchain owner also performs two separate bounded version
probes. Account for all three process calls; a source-generation test or synthetic
runner does not establish that any compiler ran. The caller must retain the
established resource admission and custody through all probes, build cleanup and
durable output disposition. This profile adds no installer or resource owner.

Parent success and unresolved-cleanup receipts retain false
`governing_scope_verified`, `governing_edition_verified`,
`contributor_completeness_verified` and `source_region_roles_verified`, along with
all existing source, meaning, independent-human-review, training/gold and corpus
admission restrictions. Their schemas remain parent-specific even when cleanup
fails. An unresolved cleanup preserves the original exception and live cleanup
handle; the caller remains responsible for keeping its resource custody until
the existing owner confirms cleanup.

A successful engineering receipt may set the existing conditional execution
flags only for the exact returned native observations:
`backend_executed`, `lean_compilation_verified`, `proof_checked`,
`kernel_proofs_checked` and `conditional_proofs_verified`. The three theorem
obligations remain conditional on the supplied donor and consumer definitions,
explicit alias, interpretation, entity carrier and evaluation time. Neither the
alias nor the statutory meaning is established as a fact. Equal unknown edition
sentinels do not establish a governing edition. A representative first-use lookup
does not establish applicability at every statutory occurrence. No training or
evaluation-gold mask becomes nonzero.

The receipt retains the original preparation's handoff unchanged, including
`parent_build_execution_adapter_not_registered`, `build_eligible=false` and its
unexecuted preparation status. Those are original preparation observations.
Actual execution belongs to the separate native receipt's process, coverage,
binary, cleanup and conditional-kernel fields. The inherited
`installed_toolchain_verified`, `toolchain_probed` and
`native_build_profile_registered` flags remain conservative false values under
the existing receipt convention; explicit `version_probes`, `binary_sha256`,
`binaries_unchanged` and `native_runtime_verified` record the actual observations.
No production admission registry is modified.

Valid regenerated pending, rejected or stale-dependency parent assessments keep
their exact status and blockers after an engineering build. Synthetic signing
credentials continue to establish fixture authentication behavior only. A native
result supplies no qualified human review, governing applicability, official
source authentication, source-to-model equivalence or statutory correctness.

The retained October 15 official FOL/TDFOL receipts document installed native
Lean `leanprover/lean4:v4.26.0` and their original fictional inputs. They provide
reusable executor/toolchain evidence, with no parent-native qualification implied.
A new parent execution needs its own admitted request, exact current source and
input pins, actual native observations and retained artifact checks. The parent
preparation tests' version string is a declaration, not an installation request
or proof of an installed compiler. Those historical observations establish no new training, statutory review or
publication result. The separately qualified current parent execution appears
below.


This implementation migrates the retained [parent-native proposal](../ARCHIVE.md)
into the existing owner. The original proposal remains immutable history. The
parent Lake dependency has its separately qualified 26-new/four-official
preparation cohort; those cases are reused, not rerun by this migration. The original migration
[focused adapter tests](../../../../../tests/unit/logic/autoformal/test_plaintext_definition_use_native.py)
use genuine current parent source/review/preparation fixtures and synthetic
compiler observations. They exercise `LegalCorpusParent`, the full original-input
commitment and parent-specific domains, while retaining original official
regressions. Synthetic success does not establish a real parent Lean build. The separate
current native qualification below uses actual installed binaries and original
owned resource/toolchain observations. No model or numerical-backend
implementation is copied into the autoformal package.

The [canonical source-migration qualification](../../../../../workspace/test-logs/federal-corpus-audits/autoformal-source-migration-20261019-01/qualification-summary.json) records 19 parent-adapter controls and three official native regressions in the corrected 88-case cohort. Original source/input replay uses genuine current owners; compiler observations in these controls remain synthetic. This engineering qualification supplies no actual parent Lean compilation or model-checkpoint parity.

## Current parent-native qualification: 2026-10-20

The [combined qualification record](../../../../../workspace/test-logs/federal-corpus-audits/parent-native-genuine-20261020-01/qualification-summary.json) binds20 corrected recipe/process controls and two separately enrolled actual parent-native cases. The FOL and TDFOL cases use authored fictional parent fixtures and real `leanprover/lean4:v4.34.1` binaries through this existing public owner. Together they perform four version probes and two offline builds, retain12 nonempty `.olean` outputs and18 exact executed input readbacks, and observe six empty axiom-dependency lists. Original source custody, observed native process cleanup, compute release, durable inventory and storage release are recorded for each successful cohort.

The ten sampled-descendant controls qualify the explicit outer validation profile for observed nested sessions, including cancellation and source-watchdog failure. A caller keeps the outer source READ until the actual owner's post-exit disposition establishes stopped observed processes and released compute. Missing evidence remains unknown; group-only historical receipts are not expanded to this new scope. Operational ownership remains with the existing optimizer/operations/shared-process owners.

Original run01 remains failed at18 passes/two metadata import-guard failures, with compute/source closed and64MiB storage retained. Request02 was unlaunched and superseded by fresh request04; no failed observation is retroactively qualified. The earlier88-case migration and its19 synthetic parent controls remain distinct historical evidence.

The actual fictional assessments still have pending review and retain their explicit donor/consumer definitions, alias, interpretation, entity-carrier and evaluation-time assumptions. Empty axiom observations do not prove those premises or the statutory interpretation. No source-to-model equivalence, original checkpoint replay, model convergence, governing legal applicability, independent human review or statutory/corpus admission follows. No model or training process ran in these new cohorts.

## Literal-parent shared conditional native profile

The existing executor also accepts the distinct `ParentSharedCorpusPreparation`
from [parent shared preparation](legal_corpus_shared_lake.md#literal-parent-shared-preparation).
Its four explicit APIs preserve the complete aggregate rather than converting
parent components into legacy norm records:

```python
parent_shared_preparation_sha256(preparation)

validate_parent_shared_definition_use_native_v1(
    preparation, *, component_inputs, expected_population,
    expected_preparation_sha256, toolchain,
)

build_parent_shared_definition_use_native_v1(
    preparation, *, component_inputs, expected_population,
    expected_preparation_sha256, toolchain, lake_executable,
    output_directory, timeout_seconds=60, cancellation=None,
)

parent_shared_compilation_receipt_sha256(receipt)
```

The preparation retains `legal-corpus-parent-shared-definition-use-preparation/v1`
and `exact-parent-definition-use-module-sharing/v1`. The separate native receipt
uses `legal-corpus-parent-shared-definition-use-native-build/v1` and
`replayed-parent-shared-definition-use-conditional-native-build/v1`. Official V2,
single-parent and shared-parent preparation/receipt domains remain distinct;
changing a schema label cannot cross those interfaces. The new preparation
commitment uses the complete parsed manifest and every sorted file text, with
the same canonical envelope recipe as the existing owner. Its pure digest
helper supplies a commitment, not validity or admission.

Supply every original `component_inputs` entry and the independently pinned,
ordered `expected_population`. One expanded 48 MiB preflight budget covers that
complete input population, its independent pins, the offered preparation and
toolchain before full-body commitment and lazy native-owner dispatch. The
canonical preparation envelope retains its 20 MiB limit, project files total
at most 8 MiB, and the preparation manifest and separate native receipt are each
bounded to 1 MiB. After genuine public regeneration, a private frozen snapshot
must still match the independent complete preparation pin before toolchain
probes or invocation. Receipt metadata and executed bytes come from that same
snapshot. Pre/post execution replay still checks the actual original callers,
physical backing sources, current review inputs and source/producer identities.

The declared aggregate ceilings are 8 component entries, 52 project files,
34 modules and 24 unique conditional theorems. These are refusal limits,
not coverage claims or a guarantee that every such population fits the byte,
node and depth bounds. The runner declares the actual module artifacts plus
actual executed project files as its output population, rather than assigning
all projects a fixed fifteen-output layout. It retains the existing 2 MiB capture,
sampled 2 GiB process-tree RSS, 128 MiB workspace, one Lean runtime thread and
caller-selected compiler wall/CPU timeout in `(0,60]` seconds. Complete source
and review replay runs outside that compiler timeout; the original admitted
outer operation and source lease must cover replay, execution and closeout.
These bounds provide no replacement admission or cleanup owner.

The receipt preserves the full ordered `population` and `components`, including
references to each child's exact retained manifest, its full intake, review
outcome/blockers and conditional premises, plus the aggregate
`input_commitment_sha256`.
`theorem_contributors` retains every ordinal/component/theorem contribution.
`conditional_theorems` is the stable first-occurrence union in component order
and each child's original theorem order. The executor requires exactly one
empty-axiom observation per unique generated theorem; duplicate component
entries keep their separate contributions without becoming extra theorem
observations or independent statutory examples. There is no fabricated
aggregate assessment or single top-level review outcome. Native success neither
changes nor combines the children's review decisions.

All actual generated modules require nonempty returned `.olean` artifacts, and
all actual generated inputs require exact executed-byte readback. The common
command, binary/source commitments, axiom parser, sampled lifecycle checks,
pre/post regeneration, failed-result persistence and original cleanup-exception
behavior remain with this executor and its existing process owner. The original
shared preparation remains preparation-only; compilation status belongs to the
separate observation receipt. Execution flags concern engineering checks of
conditional generated obligations. Definition, alias, Interpretation, carrier
and time premises remain premises; source meaning, governing applicability,
independent human review, model/training/gold and corpus admission remain open.
`parent_incremental_cache_status` remains `not_run` in this aggregate-native receipt; the separate incremental profile below does not rewrite its historical observation.

### Aggregate qualification and reuse

The [aggregate qualification record](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-native-20261020-01/qualification-summary.json) records separate cohorts:
**16/16 passed** for 16 main controls (11 new simulated-observation/early-refusal
controls and five existing regressions), and **2/2 passed** for the two
separately enrolled actual FOL/TDFOL Lean4.34.1 cases. Simulated process results
supply adapter-boundary coverage only. The actual authored projects each have
two component entries sharing one donor across two distinct physical consumers,
with 9 modules, 15 executed project inputs and 6 unique conditional theorem
observations. Across those two projects, the record binds two offline builds,
four version probes, 18 nonempty `.olean` artifacts, 30 exact executed inputs and
12 empty-axiom observations, together with original source/native/storage
closeout. These counts do not qualify a build with eight components or any broader
statutory population. The TDFOL fixtures use bounded quantified unary Boolean
definitions and explicit assumed aliases; they qualify no new modal or
norm-operator semantics.

Both actual projects retain unavailable trust and pending review. The existing
28-case shared-preparation cohort, its separately reused two physical-source
controls, and the earlier two single-parent native builds keep their original
source generations and scopes; they are not rerun or added to these aggregate
cohorts. Reuse the qualified conditional aggregate route for its supported
profile. The existing [incremental owner](legal_corpus_incremental.md#parent-shared-definition-use-profile) now has a distinct parent profile and 22 authored coordinator controls. Its separate [installed-Lean qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-native-20261020-01/qualification-summary.json) is **2/2 passed** for two authored FOL/TDFOL cases: 13 cold/0 warm/6 affected +7 reused/13 clean direct module calls per family, with exact affected/clean artifacts and real original source/review replay. The changed donor is an unreviewed `all`→`any` interpretation of unchanged physical text; its copied-text reusable branch supplies separate engineering custody rather than independent statutory evidence. The aggregate receipt above remains a separate Lake-build observation. Real review/revocation and closing physical-mutation refusals, and new source-text/lookup/producer/toolchain execution edges, retain their own remaining gates. No new modal/norm semantics, model, training, legal-meaning review or unified-corpus admission follows from these compiler fixtures.


## Bound norm definition native profile, version 1

The existing executor now has a separate route for the complete unchanged
relational norm and one conditional bound-definition occurrence described in
the [Lake guide](legal_corpus_definition_use_lake_v2.md#complete-relational-norm-with-a-conditional-bound-definition-version-1):

```python
validate_bound_norm_definition_native_v1(
    preparation, bound_report, *, expected_preparation_sha256,
    expected_bound_report_sha256, bound_definition_inputs, toolchain)
build_bound_norm_definition_native_v1(
    preparation, bound_report, *, expected_preparation_sha256,
    expected_bound_report_sha256, bound_definition_inputs, toolchain,
    lake_executable, output_directory, timeout_seconds=60, cancellation=None)
bound_norm_definition_compilation_receipt_sha256(receipt)
```

The receipt schema is `legal-corpus-bound-norm-definition-native-build/v1`;
its profile is `replayed-bound-norm-definition-conditional-native-build/v1`.
The exact five-field `bound_definition_inputs` and independent full report and
project hashes are required. Native preflight bounds the complete offered tree
before replay-owner lookup. The public Lake validator then reconstructs all
nine files and six modules from the original inputs before and after the
existing bounded offline `lake build legal` operation. Producer observations
use a separate cache domain; official V2, parent and shared-parent routes retain
their existing populations and semantics.

Successful execution may observe two conditional kernel theorems in
`instance_only` mode or three in `body_with_membership` mode, with their exact
module coverage and axiom output. The definition instance still assumes
`hDefinition`; the body theorem additionally assumes `hMembership` for the
same entity, interpretation and time. The preservation theorem checks only a
definitional alias of the unchanged complete norm. Neither a successful build
nor empty axiom dependencies establish those premises, norm truth or a
norm-driven membership consequence.

The separate receipt binds the complete frozen preparation, original report
and input commitments, mode, retained field hashes/counts, pending review
status/blockers and original false build handoff. Full alternatives, nominations,
source references and exact norm/definition bodies remain in the retained
project manifest and external replay inputs. The relational `source_binding`
remains null. All source adoption, legal meaning, governing use, applicability,
actual membership, graph/corpus admission and training/gold authority remain
unverified. Cancellation, bounded compiler timeout and unresolved native cleanup
continue to use the original resource and process owners.

**Qualification:** the [portable evidence](../../../../../docs/autoformalization/evidence/legal-ir-bound-norm-corpus-20261023.json) records separate **42-case/126-phase pure** and **two-case/six-phase actual Lean4.34.1** cohorts. Pure controls comprise 26 Lake, 13 new native and three legacy regressions against their retained original frozen source. The actual-only fixture subsequently adds `numbered=False` to `mktemp`; independent static comparison preserves every pure test/helper and all other source AST. Fresh `native-v02` exercises the repair.

Its positive build returned all nine exact source files and six nonempty `.olean` files (142,048 bytes), with three empty-axiom conditional theorem observations. The negative build produced the expected type mismatch when `hNorm` was supplied directly as `headAt` membership; it is not a general non-derivability theorem. Four original-runner invocations were observed: two version probes and these two builds. Original compute/storage and source READs closed for this successful attempt, retaining 424,599 durable bytes.

The first actual attempt, `native-v01`, was cancelled by the original strict
inventory after pytest created a convenience symlink. Compute and source READ
custody closed, while its 192-MiB storage reservation remains retained with the
preserved attempt. A later attempt must retain that disposition and must not
imply that every attempt released storage.

The pure worker uses explicit namespace profile
`bound-norm-corpus-scoped-unit-namespaces/v1`: the original seven namespace
behaviors remain, `logic.backends` is genuinely fileless, and the real
`logic.integration` and `logic.integration.reasoning` initializers are frozen
and pinned but bypassed. This qualifies namespace-scoped unit engineering,
not full package integration. The pure worker retains normal pytest assertion
behavior and compile-origin observations; it does not compare every compile
event payload. Actual-v02 explicitly uses `--assert=plain` and verifies exact
candidate compile buffers. Its bounded compiler/process evidence remains
separate from the retained first failure. No model or training work was performed.


## Complete authored parent norm: native observations

The existing native owner exposes `validate_parent_norm_native_v1`,
`build_parent_norm_native_v1` and `parent_norm_compilation_receipt_sha256` for
the [direct parent-norm preparation](legal_corpus_definition_use_lake_v2.md#complete-authored-norm-from-an-exact-parent-occurrence).
The separate receipt schema is `legal-corpus-parent-norm-native-build/v1`; its
profile is `replayed-parent-literal-complete-authored-norm-native-build/v1`.

Validation takes the typed preparation, original `correspondence`, independently
retained `expected_preparation_sha256` and `expected_correspondence_sha256`,
complete original `correspondence_inputs`, and exact `toolchain`. Building adds
`lake_executable`, a fresh `output_directory`, finite `timeout_seconds` in
`(0,60]` and optional `cancellation`. Validation executes no tool. A build uses
the existing pinned native Lake/Lean verifier, offline bounded process runner
and exclusive project/artifact/log writer. The existing explicit
`IPFS_DATASETS_BOUND_NORM_NATIVE_LAKE` test gate selects the installed tool;
actual execution still requires the original owned validation enrollment.

This route preserves four modules, seven input files and one
`original_norm_preserved` theorem. That theorem is a definitional alias identity
for the unchanged authored formula under its supplied interpretation and time;
it establishes no norm truth or source-to-typed equivalence. Definition
composition and membership remain absent. The original preparation's
`build_eligible=false` and no-build handoff remain unchanged; separate native
receipt observations describe any actual invocation.

During a build, original parent inputs and physical files, genuine opening/closing
preparation returns, the frozen invocation, actual runner outputs, binary pins, persisted
readbacks and receipt bytes remain checked through closing custody. Post-run caller/physical custody failures, while the original persistence
callbacks remain unchanged, retain the frozen observations with a false receipt
before refusal. Replaced persistence callbacks refuse before the writer; retained
output is not promised for that path. Later drift after genuine persistence preserves the written
observation and refuses a successful current-source return; it supplies no
rollback, repair or current corpus admission. Existing nine-file and shared
profiles retain their default readers and qualification scopes.

The separately [qualified native result](../../../../../docs/autoformalization/evidence/legal-ir-parent-complete-norm-native-20261024.json) records
**23 cases / 69 phases from
12 selectors**: 21 pure
controls and 2 actual Lean controls. The
shared positive build compiled the exact four modules and seven authored inputs
on leanprover/lean4:v4.34.1; its one `original_norm_preserved` observation
reported no axioms and remains a definitional alias identity. The production API
refused a rehashed root-module change before toolchain entry. A separately
enrolled original bounded runner compiled that changed root and observed the
intended type mismatch when `hAlias` was offered as norm truth; the other six
inputs remained exact.

The failed native-v01 observed 21 pure call passes and two native setup errors;
no native command started and it received zero complete-cohort/native credit.
Its original one-call storage closeout released only the 192 MiB promise and
retained all 307 files / 7,167,104 bytes. A separately reviewed control-only
DEVNULL preparation correction preceded the qualifying native-v02. These
generations and the older 68/204 pure and bound-norm native receipts remain
separate; no counts are pooled.

The accepted record binds exact collection, all phases/JUnit, four real bounded
commands, binary pins, compiled/executed source buffers and the observed
namespace/initializer scope, plus original compute/storage/source-READ closure.
Whole-package startup, unselected tests and cached third-party/stdlib bytecode
are outside that qualification.

Governing source/edition, complete source meaning, definition applicability,
statutory truth, semantic graph or Lean corpus admission, learned reconstruction
and convergence remain separate. Training and evaluation-gold masks stay zero.

The positive receipt retains `installed_toolchain_verified=false`, `native_build_profile_registered=false`, `build_eligible=false` and `toolchain_probed=false`. It separately records two successful actual version probes and `binaries_unchanged=true`; successful engineering observations introduce no global registration or default adoption.

## Parent bound definition: native contract

The extension of this existing native owner consumes the explicit
[companion parent-bound preparation](legal_corpus_definition_use_lake_v2.md#parent-literal-norm-with-a-conditional-bound-definition).
Its receipt schema is
`legal-corpus-parent-bound-norm-definition-native-build/v1`; its profile is
`replayed-parent-bound-norm-definition-conditional-native-build/v1`.
The existing official-V2, literal-parent, shared-parent, bound-norm and direct
parent-norm routes retain their original profiles, defaults and evidence.

```python
validate_parent_bound_norm_definition_native_v1(
    preparation, bound_report, *, expected_preparation_sha256,
    expected_bound_report_sha256, bound_definition_inputs, toolchain)

build_parent_bound_norm_definition_native_v1(
    preparation, bound_report, *, expected_preparation_sha256,
    expected_bound_report_sha256, bound_definition_inputs, toolchain,
    lake_executable, output_directory, timeout_seconds=60,
    cancellation=None)

parent_bound_norm_definition_compilation_receipt_sha256(receipt)
```

Use independent complete preparation and bound-report hashes and the same closed
five-field original `bound_definition_inputs` required by the companion preparer.
A build also requires an explicitly installed Lake ELF executable with its
sibling Lean binary, a fresh output directory and a finite compiler timeout in
`(0, 60]`. The receipt hash helper commits the separate receipt profile and
exact mask types; it does not admit the preparation or its legal content.

Pure validation executes no tool. A build uses the existing installed-toolchain,
bounded process and exclusive persistence owners for an offline
`lake --offline --no-cache build legal`. Each build performs two ordinary bounded
version probes and one owned Lake build. The version probes have no per-probe
owned lifecycle receipt; their bounded observations and the owned build lifecycle
remain different claims. The existing explicit
`IPFS_DATASETS_BOUND_NORM_NATIVE_LAKE` test gate does not itself authorize or run a
native campaign.

The new route keeps all nine source/input files, six expected modules and both
mode-dependent theorem populations: two for `instance_only`, three for
`body_with_membership`. The norm remains unchanged; `hDefinition` and any
`hMembership` remain unverified premises. Original preparation
`build_eligible=false`, no-build handoff, null governing interpretation, false
semantic authority and all four exact integer-zero masks remain unchanged.
Only a separate actual native receipt can describe compiler and conditional
kernel observations; it cannot establish norm truth, statutory meaning, governing
applicability, source-to-model equivalence or convergence.

Independent pins and bounded shape checks precede operation-owner discovery.
Public validation calls the genuine companion validator once; a build calls it
at opening and after the real runner returns. Each companion validation already
opens and closes original parent-bound replay. Final custody adds no extra
semantic replay. Original/detached inputs, actual delegate and runner returns,
physical files, callbacks, policy types, compiler binaries, persisted readbacks
and final receipt bytes remain fenced through the final direct encoding.
These full replays are substantial work; producer-pin caches are not validated
fixture or proof caches.

Successful persistence retains `project/`, `executed-inputs/`, `compiled/`,
`stdout.txt`, `stderr.txt`, `runner-error.txt` and `build-receipt.json`. Receipts
commit the full original preparation and report, selected mode, thin retained
manifest-field hashes, alternative/inventory counts, exact source and artifact
hashes, assumptions, theorem axiom observations and the owned build lifecycle.
They do not duplicate the whole report, norm and contexts. Failed observations
retain actual returned bytes when the unchanged persistence path permits it;
refusal supplies no rollback or successful current-source receipt. An unresolved
owned cleanup exception retains its original owner handle and false observation.

The retained R-source [integration qualification](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-norm-definition-native-integration-20261025.json) keeps two cohorts separate.
The original R-source pure cohort passed 32 selected cases / 96 phases from 16 selectors, including
two genuine public validation modes, bounded early refusals, explicitly
instrumented compiler/late-custody controls and one existing storage/default
regression. Its synthetic compiler results supply no native theorem evidence.
All selected cases use one owning-test module and shared original fixture,
avoiding interleaved module reentry.

The separate original R-source actual-native cohort passed two cases / six phases, one for each mode,
against the exact same 197-source generation. It uses genuine original validators,
pinned Lean4.34.1 and the compiler, with no validator substitution or version-cache
injection. Six observed commands comprise four ordinary bounded version probes
and two owned build lifecycles. Each project retained six nonempty compiled
modules and nine exact executed inputs. Instance/membership modes respectively
reported two/three theorem observations with empty axiom dependencies, including
the unchanged norm's definitional alias identity. This cohort adds no new native
bad-proof test; historical standalone rejection and synthetic refusal controls
keep their own scopes.

The result retains 167 actual compiled/executed Python source buffers, ten
observed namespace containers from fourteen declarations, and the declared
initializer bypasses. Whole-package startup, unselected tests, worker initial
loader compilation and third-party/stdlib cached bytecode remain outside this
qualification. Earlier failed peer-fixture, standalone retained-source and direct
parent-norm observations are preserved without pooling. Canonical producer/path
changes still require fresh original-input preparation; frozen outputs cannot be
relabelled as canonical current outputs.

At the retained native run’s cutoff, the subsequent compatibility boundary
used the already qualified
[direct parent-norm packet/index route](legal_corpus_definition_use_preservation_index_v2.md#opt-in-direct-parent-norm-preservation-index)
for its existing 23-file observations and stated source-generation limits. It
does not cover this parent-bound project’s 29 retained files. This source publication supplies no new packet/index API or proof-cache
admission; any later compatibility work retains its own evidence. Legal review, graph/corpus admission, numerical fitting and
model convergence retain their independent gates.

### Public dependency compatibility

The source/test bodies published here are the existing qualified native
extension (`6e6dd821…` / `02acd69d…`), adopted byte-exact. The original 32/96 pure and 2/6 actual-native cohorts above use their captured
`current-canonical-R-dependencies-plus-four-reviewed-native-overlays/v1`
generation. Their installed-source readback does not establish a new public
native execution: the readiness comparison identified nine dependency-path
differences beyond the two adopted owner/test files. Moving source or receipts
does not change those original producer identities.

The separate [retained c59 public pure compatibility observation](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-norm-native-public-integration-20261025.json) passed four selected cases / twelve phases from four literal selectors against 195 public dependency files plus the two byte-exact retained native owner/test overlays. One genuine public native validation exercised body-with-membership mode; the instance-only genuine validation case was unselected. Both instrumented handoff modes and an independent request-pin refusal passed. The two 29-file captures contain synthetic compiler versions, PIDs, compiled buffers and axiom stdout; they supply no new actual Lean build. Original selected compute, storage and both source READs closed. Twenty-nine other authored new cases, including both actual-native cases, remain outside this public run.


The preparer source `014dc6d2…`, old renderer `5c98152d…`, pure manifest
handoff and `build_eligible=false` remain unchanged. The separate explicit
native API does not register a global/default build profile or resolve source
meaning, governing applicability, legal-as-of decisions or learning/gold
eligibility.

A later [source-only compatibility review](../../../../../docs/autoformalization/evidence/legal-ir-parent-bound-norm-native-public-integration-20261025.json) compared upstream `8b6e7461…` with the completed `c59ce54c…` execution snapshot: 194 of 195 public dependency files were unchanged. The sole change, `legal_semantic_graph.py` (`f929572c…` → `b7d2f994…`), expands the relational depth limit from 24 to 32 while preserving the old accepted-domain algorithm, wire fields and other bounds; the new bytes exactly match the graph source in the original R qualification. This is bounded source/metadata review. No affected saved semantic graph or its depth was observed, and the combined 194-dependency/new-graph/two-overlay generation was not run. The four-case result above remains pinned to c59; no new pure run, actual Lean build or current-generation runtime qualification follows.
