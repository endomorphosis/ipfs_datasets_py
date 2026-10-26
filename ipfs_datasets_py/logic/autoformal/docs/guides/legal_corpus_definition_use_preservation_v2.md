# Concrete AST preservation in V2 definition-use projects

The [new preparation owner](../../legal_corpus_definition_use_preservation_v2.py)
extends an exact [V2 definition-use project](legal_corpus_definition_use_lake_v2.md)
with concrete preservation checks for its donor, consumer, alias and joint
fragments. The separate
[native executor](../../legal_corpus_definition_use_preservation_native_v2.py)
builds the resulting project and observes twelve concrete preservation
obligations plus the three existing conditional corpus theorems.

**Qualified on October 15, 2026:** 301 tests passed without failures, errors or
skips: 133 new integration cases and 168 unchanged standalone preservation
regressions. Separate native Lean 4.26.0 execution passed two authored family
projects, compiled all 24 modules, and checked 24 preservation plus six original
conditional theorem observations with empty axiom inventories. The
[qualification receipt](../../../../../../../artifacts/legal-ir-corpus-preservation-20261015-01/qualification-receipt.json)
binds the exact sources, requests and results. Synthetic process results in
unit tests remain separate from these actual native checks.

The new cases are covered by the [preparation tests](../../../../../tests/unit/logic/autoformal/test_legal_corpus_definition_use_preservation_v2.py)
and [executor tests](../../../../../tests/unit/logic/autoformal/test_legal_corpus_definition_use_preservation_native_v2.py).

This addition preserves the existing source/review interpretation, original
donor/consumer/alias hypotheses and pending or rejected review state. No legal
meaning, source fidelity, model convergence, review admission or proof-cache
authority follows from preparing or building the project.

## Four fragments and one original interpretation

The original supported component has two distinct documents, one explicit unary
definition in each, a declared shared applicability and an explicit assumed
alias. Its original public source, resolver, dependency, review and native
preparation validators retain ownership. Read the
[definition-use guide](corpus_definition_use_v2.md),
[combined review guide](corpus_definition_use_review_v2.md) and
[conditional native guide](legal_corpus_definition_use_native_v2.md)
for those input and trust boundaries.

The new owner replays the exact original DefinitionUseCorpusPreparation and
combined-review inputs. It then delegates each of its four original native
fragments to the existing
[standalone preservation owner](legal_native_ast_preservation.md).
That owner retains the strict parser, complete AST-value reification,
closedness check, independent denotation and unchanged native emitter.
The extension does not introduce another formula parser or reifier.

The standalone project normally defines its own interpretation namespace. A
corpus certificate must instead refer to the actual existing corpus
declaration. The new extension therefore shares **the original
LegalCorpusV2.Interpretation** and transports the standalone certificate body
with its denotation theorem directed to the original module's formula_0.
It removes the redundant copied formula declaration; it never substitutes a
new rendering for the original donor, consumer, alias or joint module.

| Role | Original declaration checked |
| --- | --- |
| donor | Original donor definition module's formula_0. |
| consumer | Original consumer definition module's formula_0. |
| alias | Original explicit alias module's formula_0. |
| joint | Original joint module's formula_0. |

Each role retains its exact family/formula/AST/emitter-body commitments, original
module and source hash, preservation module and source hash, standalone
preparation commitment, semantics/prelude commitments and three theorem names.
The ordered preservation_fragments population is donor, consumer, alias, joint.
Identical AST hashes do not make different fragments, families or source
interpretations interchangeable.

The supported native syntax remains the standalone owner's closed unary,
null-sort FOL/TDFOL subset. Unsupported terms, constructors, sorts and free
variables refuse. This extension does not expand definition-use support to
same-document multiple definitions, arbitrary normative uses, multiple donors,
cycles or missing applicability/context evidence.

## Six original modules become twelve

The original project has nine files and six modules. The extension produces
sixteen files and twelve modules:

| Files | Treatment |
| --- | --- |
| Eight original files other than lakefile.toml | Byte-identical, including original Lean sources, lean-toolchain and v2-input-bindings.json. |
| lakefile.toml | Registers both LegalCorpusV2 and LegalCorpusV2Preservation roots in the legal library. |
| LegalCorpusV2/PreservationSemantics.lean | Reuses standalone syntax/value/closedness/denotation definitions with the original corpus interpretation. |
| Four LegalCorpusV2/Preservation&lt;Role&gt;&lt;hash&gt;.lean modules | Concrete certificates directed at the four original declarations. |
| LegalCorpusV2Preservation.lean | Imports the original corpus root and all four certificates. |
| preservation-inputs.json | Retains the complete original nine-file preparation envelope, original native fragments and engineering reference contract. |

All nine original file texts, including the original lakefile, remain retained
in the complete original envelope inside preservation-inputs.json. The active
extension changes only lakefile.toml among those original paths. It does not
rewrite the original preparation object or its manifest.

The ordered module population is the six original modules, preservation
semantics, four role certificate modules and the new root. The manifest fixes
all imports, module names, sixteen file hashes and fifteen theorem names.
The imports are closed and acyclic.

Each role adds these three concrete theorem suffixes:

| Suffix | Obligation |
| --- | --- |
| native_value_exact | Complete typed syntax reconstructs the embedded original native AST JSON value. |
| native_ast_closed | The embedded typed syntax has no free variable occurrences. |
| denotation_matches_native | Independent AST denotation is equivalent to the original module's formula_0 for arbitrary carriers, interpretation and time. |

These twelve checks accompany the original three conditional theorems:
consumer_predicate_iff_donor_body, joint_of_components and
joint_matches_original. The first assumes the original donor definition and
alias; joint assembly also assumes the original consumer definition.
The alias remains a hypothesis, and a preservation theorem does not establish
that hypothesis as a legal or semantic fact.

The new manifest keeps conditional_theorems and preservation_theorems separate.
Its complete theorems list is the original three followed by the twelve new
obligations. A successful build concerns this exact population. It supplies no
universal Python emitter theorem, JSON byte-parser proof, source-prose
correspondence or model-convergence proof.

## Public APIs and original inputs

Both new owners have standard-library-only public imports. Complete
caller-controlled bounds and independently supplied commitments are checked
before lazy operation imports.

~~~python
from ipfs_datasets_py.logic.autoformal import (
    legal_corpus_definition_use_preservation_v2 as prep,
    legal_corpus_definition_use_preservation_native_v2 as native,
)

extended = prep.prepare_definition_use_preservation_v2(
    original_corpus_preparation, original_assessment_raw,
    expected_corpus_preparation_sha256=independent_original_corpus_sha256,
    expected_assessment_file_sha256=independent_assessment_file_sha256,
    review_inputs=complete_original_review_inputs,
    toolchain="leanprover/lean4:v4.26.0",
)

# Retain this commitment independently before accepting a later preparation.
expected_preparation_sha256 = prep.preparation_sha256(extended)

native.validate_definition_use_preservation_native_v2(
    extended, original_corpus_preparation, original_assessment_raw,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_corpus_preparation_sha256=independent_original_corpus_sha256,
    expected_assessment_file_sha256=independent_assessment_file_sha256,
    review_inputs=complete_original_review_inputs,
    toolchain="leanprover/lean4:v4.26.0",
)

# Call inside the established owned validation resource context.
receipt = native.build_definition_use_preservation_native_v2(
    extended, original_corpus_preparation, original_assessment_raw,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_corpus_preparation_sha256=independent_original_corpus_sha256,
    expected_assessment_file_sha256=independent_assessment_file_sha256,
    review_inputs=complete_original_review_inputs,
    toolchain="leanprover/lean4:v4.26.0",
    lake_executable=explicit_installed_native_lake_path,
    output_directory=fresh_output_directory,
    timeout_seconds=60,
    cancellation=cancellation_signal,
)
receipt_sha256 = native.compilation_receipt_sha256(receipt)
~~~

The pure owner also exports validate_definition_use_preservation_v2 with the
same validation inputs. Preparation and validation execute no compiler.

The extension uses DefinitionUsePreservationPreparation(manifest_json, files).
Both new preparation_sha256 helpers commit the full canonical envelope containing
the parsed original manifest and every sorted relative-path/UTF8-text file pair.
This differs from the original nine-file corpus commitment, exact manifest text
hash and exact original assessment file hash. Expected commitments must be
retained independently of the later incoming content.

Retain all original combined-review inputs: subject, registry, policy, reviews,
dependency manifest, component bytes and pin, original use/source byte groups,
expected review/registry/policy/manifest hashes, assessment time, observed
artifacts/pins and evidence bodies. A nested canonical hash cannot substitute
for original byte groups needed by their public validators.

The native executor publicly replays the complete extension before and after
execution, including its original corpus/source/review validation. It checks
both complete preparation commitments and preserves an immutable invoked
snapshot. A resealed changed module, AST value, interpretation, original input,
theorem population, review state or authority flag cannot replace regeneration.
Valid pending or rejected review evidence remains pending or rejected.

## Engineering reference contract

The preparation emits a sealed engineering reference contract, with scope
exact_engineering_observation_only. Its key binds the preservation profile,
toolchain, complete original corpus preparation, assessment, component,
dependency manifest, semantics, four complete role bindings, theorem population
and producer pins. The reference_key_sha256 commits the complete canonical key
material.

This contract describes an **exact key** for an engineering observation. It
does not look up, write or reuse a cache entry. It requires a successful exact
native receipt for any later successful-build claim. Its cache namespace is
legal_ir_concrete_native_engineering, and its legal_proof_cache_compatible and
proof_cache_admission_verified fields remain false. It is not a LegalProofCache@1
theorem receipt and must not be coerced into one.

The native owner optionally exposes:

~~~python
reference = native.receipt_reference(
    provided_receipt_raw,
    independently_expected_receipt_file_sha256,
)
~~~

This helper creates an existing EvidenceRef with kind RUNTIME_OBSERVATION and
review status UNREVIEWED. It checks the exact provided raw-byte hash, record CID
seals and reference-key digest. It does **not** replay a preparation, inspect
retained files, validate the historical compiler/lifecycle record, check a proof,
run a tool, establish a successful build or admit/reuse a cache entry.
It can address a claimed or failed observation without endorsing that claim.
Its metadata states these limits explicitly.

The exact raw-byte SHA and envelope CID have different meanings. record_cid
addresses the sealed record's canonical payload with its own record_cid field
excluded. It does not address the complete raw receipt file. The helper leaves
EvidenceRef.content_cid empty and keeps the record CID, reference-contract CID,
reference-key hash and full preparation commitment under named metadata fields.
It never labels the envelope CID as the CID of the full raw file.

An independently expected raw receipt commitment is essential. Self-sealing
forged bytes does not establish that their compiler or proof claims occurred.
A reference object is an address, not an artifact-readback result or proof
credential.

## Native observations and retained files

The executor delegates installed native ELF Lake/sibling Lean validation and
version probes to the existing toolchain owner. It pins binaries and producers
before and after this exact invocation:

~~~text
<verified-native-lake> --offline --no-cache build legal
~~~

The bounded runner receives all sixteen exact inputs and declares twenty-eight
output paths: twelve .olean artifacts and sixteen executed inputs.
Success requires all artifacts to be nonempty, exact input readback, the exact
command, available native runtime, a positive exact-integer PID, complete public
post-run replay and unchanged original preparations/binaries/producers.
Compiler errors, missing or extra observations, cancellation, resource failure,
truncation or unresolved cleanup prevent success.

Every one of the fifteen manifest-qualified theorem names must appear exactly
once in actual stdout as Lean's empty-axiom observation. Anchored info prefixes
must name the exact generated theorem source path. Unknown/duplicate theorems,
wrong source paths, nonempty dependencies, missing results, inline claims or
stderr-only claims do not satisfy the check. The receipt retains the complete
dependency map and parsing errors.

The native lifecycle must match the current caller PID and actual birth ticks
through the existing process identity helper, and bind the leader to that
parent, session and process group. It must confirm leader reaping, complete
sampled descendant/group tracking, no remaining tracked/group members, joined
pipe workers and workspace removal. Observed descendants outside that session
or group prevent success. Sampled ownership is not kernel containment.

The caller retains the established [owned validation resources](../../../../../docs/autoencoders/validation_storage.md)
through cleanup and durable disposition. Unresolved OwnedToolCleanupError keeps
its original exception and live ownership handle. The executor attempts to
retain its failed frozen project/refusal and re-raises that same exception.
A normal clean exit may have process_tree_terminated=false, because that field
records a forced intervention.

This version uses existing transport and sealing bounds: eight MiB for the
complete project and each retained artifact/input observation group, one MiB
for manifest and receipt, forty-eight MiB for complete original review inputs
and twenty MiB for the full canonical preparation envelope. Native bounds include
timeout in (0,60] seconds, corresponding CPU bound, sampled 2 GiB process-tree
RSS, 128 MiB workspace and 4 MiB capture/output-file limits. Bounds refuse
instead of dropping files or truncating input populations.

A complete successful build retains forty-nine regular files:

- project/: sixteen frozen inputs plus corpus-manifest.json;
- compiled/: twelve actual .olean files;
- executed-inputs/: sixteen original inputs observed in the compiler workspace;
- stdout.txt, stderr.txt and runner-error.txt: complete bounded captures;
- build-receipt.json: the separate sealed native observation.

The optional evidence reference is outside this build inventory. Existing
output is never overwritten. Frozen project/artifact transport and exact
readback use their existing owners.

The receipt separates original_preparation_state from native_observations.
The former preserves preparation booleans, original corpus/review state,
assumptions and reference contract without upgrading them. The latter contains
actual tool observations, complete theorem partitions, artifact/input hashes,
compiler identity/probes, post-run validation, lifecycle, cleanup and logs.
Text previews use at most 32 KiB source bytes per log, with explicit preview
shortening distinct from runner capture truncation.

Only a fully passed separate build can set
corpus_native_AST_preservation_proved, conditional_proofs_verified,
proof_checked, kernel_proofs_checked and lean_compilation_verified to true.
The first concerns twelve exact concrete checks; the conditional field concerns
the original three theorems under their retained hypotheses.
backend_executed separately records an observed available native process.

All source/legal/review/proof authority, assumed-alias truth, universal emitter
correctness, JSON byte parsing, source fidelity, source-to-model equivalence,
model execution/convergence, training/gold and corpus/proof-cache admission
remain false. Training and evaluation-gold masks remain integer zero.
No execution observation changes the original review, original preparation,
source records or independent legal acceptance requirements.

## Qualified examples and remaining integration

The FOL and TDFOL projects replay the complete original authored two-document
component, source/context bytes, pending review assessment and corpus preparation.
They are two projections of the same fictional component. There are zero
actual statutory or human reviews in this qualification. Each project retains
all original files except the changed Lake configuration; the complete original
nine-file envelope is also retained unchanged.

Three re-sealed mutations were refused before native execution: a wrong
preservation target, a missing certificate import and a changed embedded AST
value. A separate native diagnostic replaced the donor certificate's original
declaration target with False while keeping the original corpus and AST values
unchanged. Lean rejected that denotation theorem. Ten dependency artifacts
remain in the failed project; it has no successful build/proof credit. A
singleton Entity and Agent, time zero, and all-false atoms make the original
donor equivalence true and the replacement target false.

[Independent readback](../../../../../../../artifacts/legal-ir-corpus-preservation-20261015-01/independent-native-readback.json)
verified all 156 exports (12,178,136 bytes), reconstructed both constructor
values for every role back to the original complete AST, and checked original
source/import identities, theorem partitions, exact artifact/input/log hashes,
historical cleanup and reference contracts. It checked 154 record-seal
occurrences, sixteen all-false authority objects and 28 zero masks. Two sealed
engineering contracts, two exact raw-byte references and two address-only
UNREVIEWED helper references remain separate identities.

An initial Lake registration failure and its cancelled regression run remain
retained separately. The corrected configuration then passed both final
qualifications. The first independent reader also refused its reused
three-theorem count check; its new strict fifteen-theorem checker passed without
changing native outputs or the earlier standalone reader. Original failed
sources, requests and logs remain preserved; none was promoted.

The final native attempt used four version probes, two successful builds and
one semantic diagnostic: seven native tool invocations, with compiler
descendants tracked separately. All selected resource claims were released
after durable evidence verification through the existing owners.

The [cache compatibility audit](../../../../../../../artifacts/legal-ir-corpus-preservation-20261015-01/proof-cache-compatibility-audit.json)
defines the next boundary. Add a production retained-packet reader and typed
contextual reference validation before reuse. Then qualify an observational
projection through the existing index owners with unknown result, no authority
and no kernel-acceptance credit. Existing LegalProofCache theorem attachments
require a genuine compatible artifact and theorem-specific receipt lineage;
these engineering observations are not converted into them. Actual cache
writes, backend activation, artifact reuse, reviewed statutory correspondence,
broader logic coverage and convergence remain separate work.
