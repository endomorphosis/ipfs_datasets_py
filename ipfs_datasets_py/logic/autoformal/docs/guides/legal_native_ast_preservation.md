# Concrete native AST preservation checks

The [preparation owner](../../legal_native_ast_preservation.py)
and separate [native executor](../../legal_native_ast_preservation_native.py)
connect a complete serialized native AST to an independent Lean denotation and
the unchanged existing native emitter output. Each project prepares three
concrete obligations: exact AST value reconstruction, absence of free
variables, and equivalence between that AST's denotation and the emitted formula.

**Qualified on October 15, 2026:** 200 tests passed, with one existing optional
native-route test skipped because its installed executable was not configured.
A separate native Lean 4.26.0 run passed six projects, compiled all 24 expected
modules, and observed all 18 concrete theorem checks with empty axiom inventories.
[Independent readback](../../../../../../../artifacts/legal-ir-ast-preservation-20261015-01/independent-native-readback.json)
verified all 175 exports, including complete reconstruction of both generated
Lean AST values back to each original JSON AST. The
[qualification receipt](../../../../../../../artifacts/legal-ir-ast-preservation-20261015-01/qualification-receipt.json)
records the bounded evidence and remaining trust boundaries.

This profile establishes no statutory interpretation or model convergence.
Its proof boundary starts with an exact supplied native fragment. Original
source acquisition, source-to-AST interpretation, legal review and corpus
admission retain their existing owners and states.

## Supported native subset

The input is the complete original legal-native-family-route/v1 record
returned by legal_family_routes.prepare_native_fragment, retained as original
UTF8 JSON file bytes. The preparation owner calls that same public route again
and compares the entire regenerated record: native AST, formula, printed parse,
Lean body, lowering details and producer pins. An opaque formula or replacement
Lean expression cannot substitute for the original record.

Only declared FOL and TDFOL fragments with this closed subset are supported:

| Native node | Required structure |
| --- | --- |
| Predicate | Exactly one argument, an in-scope Variable. |
| Variable | Exact node_type, name and sort fields, with null sort. |
| UnaryFormula | Exact LogicOperator enum with ¬. |
| BinaryFormula | Exact LogicOperator enum with ∧, ∨, → or ↔. |
| QuantifiedFormula | Exact Quantifier enum with ∀, a null-sort variable and body. |

Identifiers are ASCII letters followed by ASCII letters, digits or underscores,
with a maximum length of 128. Every supported node has a closed field set.
Children, repeated subformulas and binary association retain their original
order. Nested universal quantifiers and lexical name shadowing are supported;
each predicate variable must be bound at its occurrence. The preparation limits
the tree to 4,096 counted formula/variable nodes and formula depth 32.

Existential, temporal, modal, cognitive, multiargument, function, constant and
multisorted forms require separate profiles. Unexpected fields, enum tags,
sorts, constructors or free variables refuse. This subset includes the existing
unary definition shape "forall x, head(x) iff body(x)", and also accepts other
closed formulas built from the listed constructors. Input acceptance does not
guarantee compilation within finite native resource limits.

## Three concrete obligations

The generated semantics module defines two separate data types. NativeValue
mirrors the null, string, array and object values occurring in the accepted
native AST, using canonical sorted object fields. UnaryFOL represents the
supported formula constructors with their actual predicate and variable names.

The preparation has two distinct reification paths. One walks the complete
original AST JSON value without dispatching on formula constructors and embeds
it as actualNativeValue. The other validates each supported constructor and
embeds typedNativeAst. Lean's toNativeValue reconstructs the complete native
value from that typed syntax. Constructor tags, enum wrappers, variable names,
null sorts, child order and every accepted field are included.

The semantics module independently defines denote. Predicates call the
existing Interpretation.atom with the named entity and evaluation time.
Negation, conjunction, disjunction, implication, equivalence and universal
quantification use their ordinary Lean Prop meanings. An environment maps names
to optional entities; entering a quantifier updates that name's binding. The
separate closed check rules out free variable occurrences. No inhabited carrier
assumption is introduced.

Each instance retains the **unchanged** lean_body from the replayed native
fragment and generates these three qualified theorem names:

| Theorem suffix | Exact obligation |
| --- | --- |
| native_value_exact | toNativeValue typedNativeAst = actualNativeValue. |
| native_ast_closed | closed [] typedNativeAst = true. |
| denotation_matches_native | For arbitrary carriers, interpretation and time: denote i typedNativeAst emptyEnvironment t ↔ formula_0 i t. |

The denotation never refers to formula_0. The final theorem compares embedded
syntax with the actual existing emitter's expression. It does not compare two
aliases of one generated definition. The source-bearing fragment remains
unchanged.

These are **concrete instance** obligations. They do not prove a universal
correctness theorem for every Python emitter input. They also do not prove the
Python JSON decoder, JSON-to-Lean reifier, byte parsing, cryptographic hashes,
source prose interpretation or the installed compiler's entire dependency
closure. The manifest records these trust boundaries. Kernel checking does not
turn a supplied interpretation into a legal fact.

## API and independent commitments

Public imports of both new owners use only the standard library. Operation
owners load lazily after caller-controlled input bounds and pins are checked.

~~~python
from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation as prep
from ipfs_datasets_py.logic.autoformal import legal_native_ast_preservation_native as native

prepared = prep.prepare_native_ast_preservation(
    original_fragment_raw,
    expected_fragment_file_sha256=independent_original_file_sha256,
    toolchain="leanprover/lean4:v4.26.0",
)

# Retain this commitment independently before accepting a later preparation.
expected_preparation_sha256 = prep.preparation_sha256(prepared)

checked = native.validate_native_ast_preservation(
    prepared, original_fragment_raw,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_fragment_file_sha256=independent_original_file_sha256,
    toolchain="leanprover/lean4:v4.26.0",
)

# Call within the established owned validation resource context.
receipt = native.build_native_ast_preservation(
    checked, original_fragment_raw,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_fragment_file_sha256=independent_original_file_sha256,
    toolchain="leanprover/lean4:v4.26.0",
    lake_executable=explicit_installed_native_lake_path,
    output_directory=fresh_output_directory,
    timeout_seconds=60,
    cancellation=cancellation_signal,
)
receipt_sha256 = native.compilation_receipt_sha256(receipt)
~~~

The preparation owner also exports validate_native_ast_preservation with the
same validation arguments. Preparation and validation execute no compiler.

The frozen NativeAstPreservationPreparation has manifest_json and a sorted
tuple of relative-path/UTF8-text file pairs. Both preparation_sha256 helpers
commit the complete canonical manifest-and-files envelope, including the
manifest's record CID. A commitment alone does not validate incoming content:
public validation must regenerate every field and file from the independently
pinned original fragment.

Keep these commitments distinct:

- expected_fragment_file_sha256 commits original UTF8 JSON file bytes,
  including formatting.
- original_fragment_canonical_sha256 commits the complete parsed fragment,
  serialized with sorted keys, compact separators, UTF8 and finite JSON values.
- expected_preparation_sha256 commits the complete canonical manifest and
  all seven generated file texts.
- preparation_manifest_sha256 commits exact original manifest text bytes.
- compilation_receipt_sha256 commits the complete separate observation.

A resealed changed manifest, AST value, native expression, file population or
authority flag cannot replace regeneration. The preservation input file retains
the exact original fragment text alongside its parsed value, byte length and
raw/canonical hashes.

This generic profile does **not** replay original statutory HTML, acquisition
descriptors, full review bundles or historical source-binding results. A separate
qualification driver can relate an exact fragment to retained source artifacts.
That relation must preserve original commitments and review state; it cannot
silently reseal historical source evidence with changed producers.

## Closed project and native execution

Every preparation contains exactly seven files:

| File | Purpose |
| --- | --- |
| lakefile.toml | One legal library rooted at LegalNativeAstPreservation. |
| lean-toolchain | Explicit versioned Lean toolchain. |
| preservation-inputs.json | Original fragment text, parsed value and commitments. |
| LegalNativeAstPreservation/Prelude.lean | Unchanged native interpretation prelude in the new namespace. |
| LegalNativeAstPreservation/Semantics.lean | Native value, typed AST, reconstruction, closedness and independent denotation. |
| LegalNativeAstPreservation/Instance&lt;sha256&gt;.lean | Unchanged native declaration, embedded AST values and three concrete obligations. |
| LegalNativeAstPreservation.lean | Exact root import of the instance. |

The four modules are prelude, semantics, instance and root, in that order. Their
imports are closed and acyclic. The instance name commits the original fragment
file, profile and semantics implementation. The manifest records exact
module/import populations, all seven source hashes, theorem names, producer pins,
syntax limits, source custody and trust boundaries.

The executor validates installed native Lake and sibling Lean ELF executables
through the existing toolchain owner. Their version probes must match the
explicit toolchain, and binary hashes are checked before and after building.
The exact argument vector is:

~~~text
<verified-native-lake> --offline --no-cache build legal
~~~

The bounded runner receives all seven generated inputs and declares eleven
outputs: four expected .olean files and seven executed inputs. Success requires
all four artifacts to be nonempty and every observed input to match its frozen
bytes. It also requires the exact command, native runtime, positive exact-integer
PID, unchanged binaries/producers, successful full post-run public replay and no
compiler, resource, cancellation, capture-truncation or runner failure.

Each of the three qualified theorem names must appear exactly once in actual
stdout as Lean's empty-axiom observation. An anchored info prefix naming the exact
theorem source path and line/column is accepted. Unknown or duplicate theorems,
wrong paths, nonempty dependencies, missing lines, inline claims and stderr-only
claims cannot establish a check. Full bounded captures remain retained.

The exact typed native lifecycle must confirm leader reaping, complete sampled
descendant/group tracking, no remaining tracked/group members, joined pipe
workers and workspace removal. The executor checks the current caller PID and
actual birth ticks through the existing process identity helper, the leader's
parent PID and owned session/group. An observed descendant in another group or
session prevents success.

These are sampled ownership observations. They do not attest kernel containment
or rule out an unobserved escape between samples. A normal clean exit can have
process_tree_terminated=false: that field records a forced intervention.
An unresolved OwnedToolCleanupError retains its original live ownership handle
and is re-raised unchanged. The executor tries to retain a failed frozen project
and refusal receipt before re-raising.

The caller retains the established [owned validation resources](../../../../../docs/autoencoders/validation_storage.md)
through cleanup and durable output disposition. No replacement lease,
installation, download or admission bypass is introduced. Native limits include
a timeout in (0,60] seconds, corresponding CPU bound, sampled 2 GiB process-tree
RSS, 128 MiB workspace, 2 MiB captures/output files and eleven declared outputs.
Original fragment, manifest and receipt bounds are one MiB each; the complete
project is bounded to eight MiB. Bounds refuse inputs instead of silently
truncating their populations.

## Receipts and retained artifacts

A complete successful build retains twenty-three regular files:

- project/: seven frozen inputs plus corpus-manifest.json;
- compiled/: four actual .olean files;
- executed-inputs/: seven original inputs observed in the compiler workspace;
- stdout.txt, stderr.txt and runner-error.txt: complete bounded captured text;
- build-receipt.json: the separate sealed native observation.

Existing files are never overwritten. Transport uses the existing closed-path,
ordinary-file and exact-readback owners. Original fragment and preparation
records remain unchanged.

The receipt separates original_preparation_state from native_observations.
Preparation booleans, authority, custody, trust, support profile and assumptions
remain under the former namespace. The latter records actual compiler identity
and probes, command, runtime/PID, artifact coverage, executed input readback,
post-run replay, axiom observations, lifecycle, cleanup and log hashes/lengths.
Its previews use at most 32 KiB source bytes per log. The receipt_text_truncated
flag reports preview shortening independently of runner capture truncation.

Only a fully passed separate receipt can set proof_checked,
kernel_proofs_checked, lean_compilation_verified and
native_ast_value_preservation_proved to true. Those flags concern this project's
exact three concrete obligations. backend_executed separately records an
observed available native process.

General emitter preservation, JSON byte-parser correctness, legal-source
fidelity, source-to-model equivalence, cross-family equivalence, model
execution/convergence, review, source/legal/proof authority, training/gold and
corpus admission remain false. Training and evaluation-gold masks remain integer
zero. Kernel checks do not change original preparation or source/review records.

## Qualified evidence and remaining gates

The six projects retain the earlier section 101 native fragment through FOL and
TDFOL, plus four authored formulas covering negation, mixed binary association,
repeated atoms, implication, nested quantifiers and lexical shadowing. The two
section 101 routes represent one unreviewed physical source interpretation.
Authored cases provide engineering coverage and no statutory gold. Each project
checks exact native-value reconstruction, closedness, and independent denotation
versus its unchanged existing emitted formula for arbitrary carriers,
interpretation and time.

Three re-sealed preparation mutations were refused before native execution:
changed emitted expression, missing root import and changed native AST value.
A separate bounded compiler run changed the first emitted conjunction to
disjunction while retaining the original and typed ASTs. Lean rejected the
denotation theorem, with only the two dependency artifacts produced. Independent
readback checked a distinguishing singleton-domain valuation: Head=false,
Registered=false, Active=true and Exempt=false make the original formula true
and the changed formula false. This failed project is retained separately and
has no successful proof receipt.

The readback verified complete regular-file inventories, module/import and
theorem populations, original commitments, twelve record seals, executed source
hashes, compiler/lifecycle observations and artifact/log hashes. It rechecked 28
producer files, twenty all-false authority objects and 28 zero masks. Readback
checks retained observations; it does not rerun or replace the kernel check.

The final native attempt used twelve version probes, six successful builds and
one failed semantic diagnostic: nineteen native tool invocations. Lake also
spawns compiler descendants, which the lifecycle observations track separately.
Two earlier failed
attempts remain separate evidence: a driver re-sealing error before native
execution, then a Lean reserved-identifier error producing only the prelude
artifact. Their results were not promoted. Both were fixed before the final
test and native qualification; original failed inputs and logs remain retained.

The source-review owner and its test changed after the earlier full §101 source
qualification. The [drift observation](../../../../../../../artifacts/legal-ir-ast-preservation-20261015-01/producer-drift-observation.json)
records this explicitly. This contribution regenerates the entire unchanged
native fragment with current native owners; it does not replay or requalify the
historical full source/review bundle against those changed review producers.

Next connect these concrete certificates to compatible versioned corpus
projects and proof-cache references, preserving exact statement, interpretation,
source, dependency and toolchain identities. A general emitter theorem, raw JSON
byte-parser correctness, independently reviewed law-to-AST correspondence,
broader logic constructors and model convergence remain separate work.
