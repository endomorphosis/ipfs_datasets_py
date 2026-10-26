# Shared definitions and conditional Lean composition

`legal_corpus_shared_lake.py` extends graph-bound preparation by regenerating
every independently pinned candidate through `legal_corpus_lake`, then delegating
standalone definition and norm lowering to the unchanged native family routes
and renderer. Reports, graphs, semantic identities and source offsets are retained.

The profile `exact-source-scoped-unary-definition-sharing/v1` supports the
existing section-local unary `means` definition and universally guarded O/P/F
grammar. Unsupported rows, native identity collisions and overflow refuse the
complete batch without filtering or renaming. Original file hashes remain
distinct from native canonical JSON hashes.

## Exact sharing and provenance

A sealed sharing key binds source version, composition scope, exact definition
declaration, rebound AST, symbol rebinding and every definition/scope physical
origin. It includes the paragraphs those roles intersect, excluding unrelated
norm paragraphs. Equal labels or ASTs from other editions or repeated physical
occurrences cannot replace these inputs. All contributing candidate,
interpretation, definition, term and symbol record CIDs remain explicit.

Each `LegalCorpus.Definition<digest>` module emits its definition once. Each
`LegalCorpus.Norm<digest>` imports that definition, emits its exact native norm,
and supplies `jointAt`, their conjunction. The preparer checks that these are
the original joint AST's ordered children. `original_joint_binding` preserves
every source role/geometry, graph assertion and definition-use edge. Stable
module names follow content identities; root imports preserve population order.

The package has one native parameterized Prelude and a complete root. Its
manifest binds every module, original joint AST/body identity, contributor and
source file. Existing one-MiB manifest and eight-MiB input/project bounds apply.
Up to 64 candidates and 64 shared definitions permit at most 130 compiled
modules including Prelude/root. Not every such population fits the other
bounds; exceeded byte/depth/node limits refuse without truncation.

Orchestration source changes produce new preparation pins and manifest CIDs,
even when the generated Lean source stays identical. Archived preparations
retain their historical owners and are regenerated under the current owner.

## Conditional theorem

Each norm's `consequence_of_definition` has three premises under one
interpretation and evaluation time:

1. The exact universal definition holds.
2. The universal category-guarded norm holds.
3. The declared definition body holds for the supplied entity.

It derives the parameterized modal action for that entity by the definition's
biconditional and the norm's implication. Category activation stays outside
the modality. O/P/F remain arbitrary supplied modal interpretations. The
theorem does not conclude actual action truth or statutory truth, and neither
the definition nor norm is introduced as an axiom or a proved fact.

## Preparation and actual build

`prepare_shared_definition_corpus` and `validate_shared_definition_corpus`
perform native parsing/lowering and complete deterministic regeneration.
Public import initializes no session, compiler, backend or numerical model.
`write_shared_definition_corpus` and `load_shared_definition_corpus` reuse the
existing closed local transport: independent manifest pins, exclusive writes,
symlink/traversal refusal and exact complete readback.

`build_shared_definition_corpus` accepts the immutable preparation and original
independent inputs. Callers acquire the existing shared validation lease and
may pass its cancellation signal. The existing verifier checks explicit
installed native Lake/Lean binaries, version and hashes. The common bounded
runner compiles the exact files with `--offline --no-cache build legal`, one
Lean runtime thread, at most 60 seconds wall/CPU, two GiB sampled process-tree
RSS and 128 MiB private workspace.

Success requires actual process execution, the exact command, unchanged binary
pins, nonempty `.olean` files for every expected module and an empty printed
axiom dependency list for every conditional theorem. Truncation, cancellation,
resource failure or missing coverage prevents success. A fresh output contains
the exact source project, captured expected compiled artifacts and sealed
receipt. Native ELF/version checks retain the existing verifier's boundary;
they do not independently authenticate the full installed Lean distribution.

Returned executions retain their exact frozen source project, captured expected
artifacts and failed receipt when post-run regeneration fails or a compiler
binary disappears. They cannot acquire compilation qualification through that
failure. Workspace cleanup and execution errors also prevent success. The
runner's `process_tree_terminated` field records forced termination; a naturally
exited successful process may report false there.

Successful receipts can verify compilation and conditional obligations. Source
authenticity, reviewed legal meaning, context closure, statutory admission,
training qualification and legal proof authority remain false. The additive
[incremental compilation owner](legal_corpus_incremental.md) connects these
modules to the existing LegalIR pass manager, verifies the selected installed
library closure and retains separate fresh/reused artifact evidence. Cross-section
resolution, broader operators, a reviewed connected pilot and authenticated
toolchain release provenance remain separate work.

## Literal-parent shared preparation

The separate `ParentSharedCorpusPreparation` profile,
`exact-parent-definition-use-module-sharing/v1`, accepts complete original
parent combined-review inputs. Use
`prepare_parent_shared_definition_use_corpus_v1`,
`validate_parent_shared_definition_use_corpus_v1`,
`write_parent_shared_definition_use_corpus_v1` and
`load_parent_shared_definition_use_corpus_v1`; legacy norm APIs retain their
original schema and inputs.

Supply a plain list of one to eight component dictionaries with exactly
`assessment_raw`, `expected_assessment_file_sha256` and `review_inputs`,
plus an independently pinned ordered `expected_population` list with exactly
`component_cid` and `assessment_file_sha256` per row, and one explicit Lean
toolchain version. Replay delegates every complete child to the existing parent
definition-use owner. Do not synthesize `paragraph_indices` or `norm_record`.

A definition module is shared only when its exact endpoint source/preparation
identity, native fragment, imports and complete module bytes agree. Donor and
consumer roles and every contributor ordinal remain explicit. Identical text at
different physical source regions stays distinct. Repeated component inputs
remain repeated contributions with separate manifest/binding sidecars; they are
not distinct statutory examples.

The project retains each exact child manifest and original input-binding bytes.
Each child's `original_file_mapping` identifies retained filenames and uses
null for the original lakefile and root, which the aggregate replaces. One
`LegalCorpusParent` root imports the unique joint modules in stable order;
a closed deterministic topological order covers Prelude, definitions, aliases,
joints and root. Sharing does not discharge any child's definition, alias,
Interpretation, carrier or time premises, establish a globally satisfiable
interpretation, or combine separate review results into an admission decision.

One expanded 48 MiB budget covers the entire input population, expected pins,
toolchain and offered output before full-body hashing. The existing project
transport limits remain eight MiB of files and a one-MiB bounded manifest, with
at most 52 project files plus the separate corpus manifest. Populations below eight can still exceed byte, depth or
node limits and refuse as a whole. Caller, detached input and offered-output
commitments are compared at the closing boundary. Successful operations also
replay each child's physical backing sources; this is sequential bounded
observation, not an atomic multi-file filesystem snapshot.

For N component entries, successful prepare/validate/load call
`prepare_parent_definition_use_corpus_v1` directly 2N times; write calls it 3N
times including closed readback and the final physical-source replay. N includes
repeated entries; these counts do not include additional nested endpoint/context
replays inside each child call. Keep the original cooperative source lease through
the complete admitted operation. Source/review checks and their cost must not
be omitted to fit a smaller execution deadline.

This profile prepares and transports files only. The existing native owner now
has a separate [shared-parent conditional execution profile](legal_corpus_definition_use_native_v2.md#literal-parent-shared-conditional-native-profile),
whose own receipt records actual execution without rewriting this preparation's
unexecuted status. The legacy shared builder/cache cannot consume this profile
by changing a schema label. The same [incremental owner](legal_corpus_incremental.md#parent-shared-definition-use-profile) now exposes a distinct parent profile with 22 authored coordinator controls; its native qualification remains a separate evidence scope.

### Qualification and remaining execution

The [main qualification record](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-preparation-20261020-01/qualification-summary.json) is **28/28 passed**: 28 cases, comprising 21 new preparation controls and seven existing regressions (four legacy, two parent and one official). The separate [physical-source closeout qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-physical-close-20261020-01/qualification-summary.json) supplies two independently qualified prepare/validate mutation-refusal cases on the same executing shared-owner and test source. Those two cases are reused without rerunning them; they do not cover a separate late-transport load/write race or an atomic filesystem snapshot. The cohorts qualify bounded preparation and transport engineering, with no model, training, aggregate Lean build, parent incremental cache or statutory-meaning result.

### Separate aggregate native execution

The [new aggregate native record](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-native-20261020-01/qualification-summary.json) is separate from the preparation cohorts above: **16/16 passed** for 16 main controls (11 new simulated/early and five existing regressions), plus **2/2 passed** for two actual authored FOL/TDFOL builds. Each actual project shares one donor across two physically distinct consumers, with 9 modules, 15 executed inputs and 6 unique conditional theorem observations; neither capacity for eight components nor statutory correctness is qualified. Complete child intakes, pending review, explicit premises and repeated contributor ordinals remain intact. The [native API guide](legal_corpus_definition_use_native_v2.md#literal-parent-shared-conditional-native-profile) explains the distinct receipt and limits. The separate [parent incremental installed-Lean qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-native-20261020-01/qualification-summary.json) is **2/2 passed** for two authored FOL/TDFOL cold/warm/affected/clean cases: 13 cold/0 warm/6 affected +7 reused/13 clean direct module calls per family, with real original source/review replay and exact affected/clean artifacts. This changes an unreviewed donor interpretation on unchanged physical text; the copied-text reusable custody branch is not independent statutory evidence. The preparation and aggregate-native cohorts above keep their own counts and profiles. Real review/revocation and closing physical-mutation refusals, new modal/norm semantics, statutory admission and model/training improvement remain unqualified.

### Same-operation replay cost

A source-only follow-up identified repeated parent replay in corpus_definition_use_review_v2, corpus_definition_review_v2 and legal_statutory_context_v2: endpoint definition and per-occurrence context validation repeatedly call legal_semantic_graph.bind_parent_source_occurrence, rebuilding the same parent corpus. Text-view, cache-occurrence, sentence-candidate and lineage checks in turn reopen selected parent rows and hash the complete independently pinned file. This is call-graph analysis, not measured timing attribution. Investigate bounded same-operation reuse in the existing binding/parent owners, preserving full population/input commitments, source/FD/path/producer-change checks, current review/revocation replay and final physical fences. Do not replace these with a persistent trust cache or remove closing checks to shorten qualification.
