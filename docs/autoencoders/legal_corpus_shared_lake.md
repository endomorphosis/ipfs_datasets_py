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
