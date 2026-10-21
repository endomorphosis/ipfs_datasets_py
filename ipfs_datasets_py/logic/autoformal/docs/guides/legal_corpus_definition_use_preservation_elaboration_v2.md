# Native theorem-type elaboration for V2 corpus preservation

The [elaboration preparation owner](../../legal_corpus_definition_use_preservation_elaboration_v2.py)
adds a native type-checking harness to a complete replayed
[typed theorem lineage](legal_corpus_definition_use_preservation_theorem_lineage_v2.md).
The [native executor](../../legal_corpus_definition_use_preservation_elaboration_native_v2.py)
clean-builds the generated project and retains structured observations of the
actual original theorem types and namespace-preserving aliases.

The earlier lineage remains unchanged: its statements are opaque
`lean_declaration_header` source identities in the
`engineering_corpus_preservation` domain. This adapter asks Lean to elaborate
complete declaration commands in their original namespaces. It does not treat
the literal header as an independently parsed proposition, replace the original
claim statement, or construct an executable backend request.

## Prepare and validate the additive project

`prepare_definition_use_preservation_elaboration_v2` takes the genuine typed
lineage, immutable 49-file packet, typed original corpus preparation, original
assessment bytes and all eight packet-reader arguments. It also requires
independently expected SHA256 values for the exact lineage and packet-observation
bytes. Complete current source/review and typed-lineage replay remains mandatory.

The frozen `ElaborationPreparation` contains `manifest_json` and seventeen
sorted immutable path/text pairs. `preparation_sha256`, also exposed as
`elaboration_preparation_sha256`, commits the complete manifest text and all
seventeen files. Computing the commitment does not validate the preparation.

`validate_definition_use_preservation_elaboration_v2` additionally requires
`expected_elaboration_preparation_sha256`. It regenerates the entire preparation
through current public owners and compares the complete type-sensitive envelope.
Source edits, changed bindings, resealed authority changes or incomplete inputs
cannot substitute for that replay.

The project retains the original sixteen inputs. The sole change to an existing
file appends `LegalCorpusV2Elaboration` to the Lake library roots alongside
`LegalCorpusV2` and `LegalCorpusV2Preservation`. The additional file,
`LegalCorpusV2Elaboration.lean`, imports Lean and both original roots. The
expected project contains thirteen compiled modules. Original source bytes,
theorem identities, four native AST instances, interpretation, semantic bodies,
review state and dependency bindings remain separately committed.

For each of the fifteen original declarations, the harness:

1. Copies the complete exact declaration header inside its original namespace,
   changing only the theorem's short name to its generated alias name.
2. Supplies the original fully qualified theorem with every ordered carrier,
   interpretation, time, entity and proposition-hypothesis argument explicitly.
3. Requests the alias's axiom inventory and runs the closed type-check command
   against the original and alias theorem names.

The manifest retains fifteen `probe_bindings`, including both headers, names,
argument order, source-entry references and original claim/obligation/premise
identities. It keeps the fifteen original and fifteen alias theorem names as
separate ordered partitions.

## What the native checker establishes

The generated Lean helper requires `ConstantInfo.thmInfo` for both declarations.
It checks that their complete types have no free variables, metavariables or
loose bound variables, and that their universe-parameter lists match exactly.
`Expr.equal` requires exact expression identity, including binder names and
implicitness annotations. `Lean.Kernel.isDefEq` separately checks kernel
definitional equality.

The helper also calls `Lean.Kernel.check` on each type and requires `Sort 0`,
then checks both fully instantiated theorem constants against their captured
types. The generated alias proof is itself compiled in the fresh source build.
Pretty-printed type text, a declaration-name match or a claimed success flag
cannot replace these checks.

The supported corpus still has five explicit proposition-premise occurrences
across two declarations per family. The donor and alias premises in
`consumer_predicate_iff_donor_body`, and donor/consumer/alias premises in
`joint_of_components`, remain parameters. Universal carrier, interpretation,
time and entity binders remain separate. Empty axiom inventories do not prove
those hypotheses or establish their legal interpretation.

## Structured type observations

Each successful command emits one `CORPUS_TYPE_CHECK:` record using schema
`legal-corpus-v2-native-theorem-type-check/v1`. Its closed fourteen-field record
contains the original and alias names, both complete structured types, both
universe-parameter lists and these seven checks:

- `expr_equal`
- `kernel_defeq`
- `original_kernel_check`
- `alias_kernel_check`
- `closed_types`
- `prop_type`
- `level_params_equal`

All seven must be the Boolean `true`. The executor also compares the complete
canonical type and universe representations, checks the exact expected name
pair, and rejects duplicate, missing or unknown observations.

| Representation | Closed supported grammar |
| --- | --- |
| `Name` | Anonymous root, string component or natural-number component, with the complete parent chain |
| `Level` | Zero, successor, maximum, impredicative maximum or a declared named universe parameter |
| `Expr` | Bound variable, sort, constant with universe levels, application, lambda, universal binder, let expression, natural/string literal or projection |

Binder records retain their names, implicitness, types and bodies. Bound-variable
indices must refer to a surrounding binder; universe parameters must occur in
the explicit declared list. Free variables, metavariables, expression metadata,
unknown constructors and extra fields refuse this observation profile. This
bounded JSON grammar validates the captured representation; it is not a Python
implementation of Lean elaboration or kernel type checking.

## Execute within the existing owned resource boundary

`build_definition_use_preservation_elaboration_native_v2` accepts the preparation
and all original lineage/packet/source/review inputs, with
`expected_elaboration_preparation_sha256`, `expected_lineage_sha256`, the packet
arguments, explicit `lake_executable`, fresh `output_directory`, optional
`cancellation` and finite `timeout_seconds` in `(0, 60]`.

Run project imports, validation and execution through the existing frozen-request
`scripts/ops/legal_ir/run_owned_validation.py` workflow. The caller retains its
resource reservation through native cleanup and durable output disposition.
This adapter introduces no scheduler, connection, cache or resource owner.

The executor validates the full preparation before and after execution, checks
producer compatibility, and rechecks complete lineage, packet, argument and
original corpus identities. It reuses the existing installed-toolchain owner to
hash and version-probe the sibling Lean/Lake ELF pair. Those binary identities
must match the independently pinned original packet, and must remain unchanged
after the build.

The existing `BoundedToolRunner` executes
`lake --offline --no-cache build legal` in a fresh isolated owned workspace.
Its inputs contain seventeen source/configuration files and no retained
`.olean` files. The limits retain the existing one-thread, 2 GiB native memory,
8 MiB input, 128 MiB workspace and 4 MiB combined capture bounds. Exact output
coverage requires all seventeen executed inputs and thirteen nonempty compiled
artifacts. The original fifteen and new fifteen declarations each require one
recognized empty-axiom observation, with no additional axiom evidence hidden in
stdout or stderr.

Full structured records are retained separately in `native/type-checks.json` as
canonical JSON bounded to 1 MiB and depth 96. The sealed receipt keeps compact
per-theorem names and check flags, plus byte counts and SHA256 values for each
complete record, original/alias type and universe-parameter list. Its
`type_checks_file` descriptor commits the exact complete standalone payload.
The original corpus-record depth bound of 20 remains unchanged. A detached
canonical snapshot binds the compact summaries to the retained full bytes.

The receipt also records complete source/artifact/log commitments, binary/probe
observations and the existing sampled native lifecycle.
Successful qualification additionally requires the genuine bounded result,
expected command, ordinary zero exit, complete capture, unchanged inputs and
producers, exact process ownership and confirmed workspace/process cleanup.
Frozen project inputs, partial artifacts, full stdout/stderr/runner-error files
and a failed receipt are retained for completed compiler or capture-validation
failures. Rejected or oversized captures cannot become partial successful type
observations; the full bounded process logs remain separate evidence.
An unresolved cleanup exception is rethrown with its original cleanup owner;
retaining diagnostics does not release that ownership.

## Toolchain and authority boundaries

The installed standard library and dynamically loaded compiler libraries remain
explicit external trust premises. The existing installed-toolchain contract
pins the sibling ELF pair and project sources/artifacts; it does not inventory
the complete installed library closure.
`installed_stdlib_artifact_closure_verified` therefore remains `false`.

A successful new receipt can report the bounded fresh compilation and exact
type/kernel checks. It grants no source, legal, review, proof-cache, model or
training authority, and keeps training and evaluation masks at integer zero.
The original packet, historical native receipt and opaque typed lineage keep
their earlier meanings and bytes.

No `FormalizationArtifact`, `BackendRequest`, `BackendAttempt`, `ProofResult` or
typed `ProofReceipt` is constructed. The earlier observational database is not
opened or written. Typed theorem-receipt issuance still needs a separately
qualified request/attempt/result/output binding, followed by exact legal
artifact-to-obligation binding where legal admission is requested. Compiler
artifact reuse, elaborated term-dependency qualification, reviewed statutory
correspondence, token savings and model convergence remain separate gates.

That bridge must project a new claim and obligation from the exact captured
kernel type and universe parameters, retaining its original header lineage and
every hypothesis binding. The opaque header claims keep their original
identities and false elaboration flags. A theorem request must exist before its
native execution; these observations have no request digest and cannot become
retrospective request-scoped receipts. Any shared build serving multiple
requests needs an explicit, qualified mapping. Missing Lean step-count or peak
memory measurements must not be represented as observed zeros.

## Qualification on October 16, 2026

The [qualification receipt](../../../../../../../artifacts/legal-ir-corpus-elaboration-20261016-01/qualification-receipt.json)
records **86 passing tests**, with no failures, errors or skips: 41 elaboration
cases and 45 existing theorem-lineage regressions. Unit historical packets and
machine captures are synthetic. A separate owned native run clean-built both
actual retained authored FOL/TDFOL source projects: 26 project modules, thirty
original/header-alias type pairs and sixty empty-axiom observations. All ten
explicit proposition-premise occurrences remain parameters.

The native negative changed one zero-parameter `native_ast_closed` alias to
`True` with proof `trivial`. Its alias proof compiled and retained an empty axiom
inventory, while the exact type comparison rejected it with `corpus type
mismatch`. The negative retained all twelve original compiled modules, fourteen
other type observations and thirty empty axiom inventories; its failed probe
root has no compiled artifact. Its observations receive no successful-build
credit.

The [independent readback](../../../../../../../artifacts/legal-ir-corpus-elaboration-20261016-01/independent-elaboration-readback.json)
verified all **293 exports** (26,838,301 bytes), reconstructed both complete
preparations and alias bindings, checked full structured payloads against stdout
and every compact reference, and checked artifact, log, tool and sampled
lifecycle bindings. It did not rerun Lean. All 131 earlier exports, 98 original
packet files, ten protected owners and the closed observational database remain
unchanged. Actual native invocation counts are four version probes, two
successful builds and one deliberate failed control.

Two initial launcher refusals occurred before worker startup because required
empty attempt roots were missing; the identical frozen requests ran after those
roots were created. The initial unit run passed 85 overlapping cases. Its native
companion failed when deep type data exceeded the existing sealed-record depth
limit, before native logs and artifacts were retained. That failure and its
source snapshots remain unqualified evidence. The corrected standalone-payload
design passed the full final suite, including the new depth regression, and the
complete native replay above. All four selected resource reservations were
durably released with failed evidence preserved. New typed proof receipts,
backend requests, cache writes, statutory reviews and human reviews remain zero.

The next [closed kernel claim and planned request profile](legal_corpus_definition_use_preservation_kernel_claims_v2.md)
replays these retained observations into new fully quantified engineering claims
while preserving the original opaque header claims. It prepares prospective
typed requests without rerunning Lean or issuing proof receipts. Resource
telemetry and genuine request-bound execution remain separate qualification work.
