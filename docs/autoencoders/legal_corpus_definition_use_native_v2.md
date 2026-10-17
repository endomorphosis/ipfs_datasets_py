# Conditional native execution for V2 definition use

The separate [native executor](../../ipfs_datasets_py/logic/autoformal/legal_corpus_definition_use_native_v2.py)
builds the existing nine-file, six-module definition-use preparation and observes
three conditional Lean theorem checks. It preserves the original preparation,
assessment, review outcome and `build_eligible=false`. Its compilation receipt
records an engineering observation; it does not admit a statutory
interpretation, graph, proof cache entry, training example or unified corpus.

Qualification passed **109 focused tests** and two authored native projects.
The implementation and its
[focused tests](../../tests/unit/logic/autoformal/test_legal_corpus_definition_use_native_v2.py)
use the frozen resource-owned validation path. Synthetic process
results in unit tests are separate from the actual native theorem checks. The
[authored native driver](../../../../artifacts/legal-ir-definition-use-native-20261015-01/run_authored_native_definition_use.py)
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

The [native baseline](../../../../artifacts/legal-ir-definition-use-native-20261015-01/baseline.json),
[initial owner design](../../../../artifacts/legal-ir-definition-use-native-20261015-01/owner-design.json)
and [parent-binding amendment](../../../../artifacts/legal-ir-definition-use-native-20261015-01/owner-design-parent-binding-amendment.json)
record the implementation boundary. The
[frozen focused-test request reference](../../../../artifacts/legal-ir-definition-use-native-20261015-01/test-request-reference.json)
identifies the independently pinned owner, tests, selected source files and
resource-owned check. The [test receipt](../../../../artifacts/legal-ir-definition-use-native-20261015-01/test-receipt.json)
records **109 passed, zero failures, errors or skips**, including synthetic
process-boundary controls. The
[authored driver](../../../../artifacts/legal-ir-definition-use-native-20261015-01/run_authored_native_definition_use.py)
and [independent readback script](../../../../artifacts/legal-ir-definition-use-native-20261015-01/read_authored_native_outputs.py)
performed the separately recorded native qualification and data-only readback.

Installed Lean 4.26.0 built both family projects, producing twelve nonempty
module artifacts and eighteen unchanged executed input readbacks. All six
conditional theorem instances emitted the required empty-axiom messages. Eleven
driver checks included two resealed pre-build refusal controls. Two build
commands and four native version probes ran in total; no negative native build
is counted in this phase. Both successful native-phase validation reservations
were durably released.

The [independent readback receipt](../../../../artifacts/legal-ir-definition-use-native-20261015-01/independent-authored-native-readback.json)
verified all 98 files (6,940,049 bytes), thirty producer sources, four fixture
sources, 906 sealed-record occurrences representing 273 unique CIDs, sixty
all-false authority objects, 36 strict integer-zero masks and 1,609 false
semantic fields. Each family retains thirteen physical contexts with 78 slots
and the same pending assessment. Recorded sampled lifecycle observations,
binary/source pins, logs, module coverage and conditional premises matched.
The readback imported no project owners and did not reexecute Lean.

The [qualification receipt](../../../../artifacts/legal-ir-definition-use-native-20261015-01/qualification-receipt.json)
binds these results. The earlier integration's symlink case remains separately
unqualified; its interrupted selector attempt and full 250-MB retained claim
are recorded in the [integration guide](definition_use_v2_integration.md).

The qualified authored endpoints are fictional examples in FOL and TDFOL, with
unavailable trust and `reviews=[]`. They do not add a second actual statutory
source, supply a legal reviewer or close the actual sampled source's pending
population. Actual source-first interpretation, combined legal/formal review,
source-equivalence proofs, learned-model training and convergence, and any
unified corpus publication remain separate work.
