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

### Complete historical public replay input bytes

The existing parent Lake owner provides `encode_parent_replay_value_v1` and
`decode_parent_replay_value_v1`. These bounded bytes reuse its original typed
input-commitment stream: collection counts, sorted unique dictionary string
keys, exact byte/string/integer/float bodies and distinct null/true/false tags.
Immutable bytes, Unicode and scalar types survive decoding; dictionary keys
have canonical order. This is ordinary data transport, with no executable
serialization or validation capability. The [parent preparation guide](legal_corpus_definition_use_lake_v2.md)
describes the preparation owner and its original review contract.

Use `export_parent_shared_replay_inputs_v1` to retain the complete original
public arguments for an independently pinned shared preparation. Export calls
the unchanged genuine source/review regeneration, checks the exact offered
project, and retains its existing caller/detached/offered closing fences and
successful-boundary physical-source replay. It preserves original assessment
bytes, public signatures, public keys, registry, policy, explicit evaluation
time, evidence, dependency manifest, physical locators and independent pins.
It neither requires private signing keys nor regenerates credentials.

```python
import hashlib
from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared

# Keep these original input/project commitments independently of the payload.
# component_inputs, expected_population and toolchain are the original inputs.
payload = shared.export_parent_shared_replay_inputs_v1(
    preparation, component_inputs=component_inputs,
    expected_population=expected_population, toolchain=toolchain,
    expected_manifest_sha256=expected_manifest_sha256,
)
# Transfer these byte pins independently, alongside the prior input/project pins.
payload_sha256 = hashlib.sha256(payload).hexdigest()
payload_bytes = len(payload)
replay_inputs = shared.load_parent_shared_replay_inputs_v1(
    payload, expected_payload_sha256=payload_sha256,
    expected_payload_bytes=payload_bytes,
    expected_input_commitment_sha256=expected_input_commitment_sha256,
    expected_manifest_sha256=expected_manifest_sha256,
)
# replay_inputs contains only component_inputs, expected_population and toolchain.
```

The closed envelope has exactly `schema`, `profile`, `manifest_sha256`,
`input_commitment_sha256` and `inputs`. Its schema is
`legal-corpus-parent-shared-replay-inputs/v1` and profile is
`historical-parent-shared-public-replay-inputs/v1`. The loader checks strict
independent length and SHA256, every envelope/root/component shape, the
toolchain/population joins and the complete recomputed input commitment. It
returns detached historical arguments only. Loading opens no physical source,
replays no review and supplies no current-trust, native or proof authority.

Keep four identity roles separate: payload SHA256 identifies exact transport
bytes; the existing typed input commitment identifies the complete original
public argument root; manifest SHA256 identifies exact UTF-8 preparation
manifest bytes and its file-hash binding; the native owner's full preparation
and compilation-receipt identities have their separate recipes. None can be
substituted for another. A caller reproducing the historical project must invoke
the unchanged public preparation/validation APIs and compare the regenerated
manifest with its independently retained pin. Later build/cache reuse also
needs explicitly supplied current source/review/revocation context. Saved
registry/policy/time describe the original context; do not silently override a
current decision with them. Changing that context requires explicit new inputs
and any resulting new project generation.

Changing these source owners changes their producer pins and therefore the
preparation generation. The unchanged typed commitment/hash recipe does not
preserve an older manifest whose producer pins differ. Earlier Lean/cache
receipts remain historical; this transport cohort performs no recompilation
and supplies no qualification for reusing old native artifacts under new owners.

The wire ceiling is separately bounded at 64 MiB; `max_bytes` is an exact
positive integer that can only lower it. The original 48 MiB expanded tree,
1,000,000-node, depth-48 and 4,096-character key limits stay in force, including
the envelope on codec intake and the offered output on export capture. The
existing eight-MiB project and one-MiB manifest limits are unchanged. The decoder
checks declared lengths, UTF-8/JSON expansion and collection growth before body allocation;
malformed, oversized, noncanonical, truncated or trailing frames refuse. Bounds
do not promise that every otherwise supported population fits the transport.

Retain the complete separately pinned physical artifact population at its
original locators. These bytes copy no source files, rewrite no paths, publish
no sidecar or Hub artifact, change no default cache/native path and settle no
legal source, edition, meaning or applicability question. Use the separately
qualified [local file APIs](#bounded-local-historical-replay-files) below for
explicit bounded storage. Hub publication, physical-artifact transport,
relocation/current-context policy and further native invalidation remain separate.

The [closed focused qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-replay-transport-20261020-01/qualification-summary.json) records
**61/61 passed** selected controls with original source/native/storage
closeout and exact qualified source installation. Fictional source and test
credentials remain explicit. The cohort performs no Lean build, model execution
or training and qualifies no statutory fidelity, source-to-model equivalence or
model convergence. Earlier preparation, aggregate-native and incremental cohorts
retain their original scopes and counts.

### Bounded local historical replay files

The same shared owner now provides `write_parent_shared_replay_inputs_file_v1`
and `read_parent_shared_replay_inputs_file_v1`. They store/read the already
exported immutable payload under all four independently retained pins. Both
APIs transport historical data only: writing a valid saved payload does not
rerun source/review checks or make a saved registry/policy/time current. Use
the existing genuine exporter separately when creating a new payload; retain
unchanged public preparation/validation and current-context decisions before
any native build/cache reuse.

```python
from ipfs_datasets_py.logic.autoformal import legal_corpus_shared_lake as shared

# The parent directory already exists; this destination must be new.
# Retain these pins separately from the file and from any returned pin copy.
pins = dict(
    expected_payload_sha256=payload_sha256,
    expected_payload_bytes=payload_bytes,
    expected_input_commitment_sha256=expected_input_commitment_sha256,
    expected_manifest_sha256=expected_manifest_sha256,
)
stored_pins = shared.write_parent_shared_replay_inputs_file_v1(
    payload, destination, **pins)
assert stored_pins == pins
replay_inputs = shared.read_parent_shared_replay_inputs_file_v1(
    destination, **pins)
```

Writer argument order is `(payload, path)`; the reader accepts `(path)` with
the same four keyword pins and optional lower-only `max_bytes`. The writer's
ordinary four-field pin dictionary copies those caller-supplied `expected_*`
values. It is neither a signed receipt nor a replay/trust capability. Do not
derive a receiver's independent expected identities solely from the received
file or an untrusted returned dictionary. The reader returns only detached
`component_inputs`, `expected_population` and `toolchain` data.

All pin types and the selected bound are checked before file opens; the writer
also runs the unchanged public bytes loader before any filesystem mutation.
The existing path owner rejects traversal and symlink directory components.
The parent directory must already exist. Descriptor-relative opens use
`O_NOFOLLOW`, `O_NONBLOCK` and `O_CLOEXEC`. The reader checks regular-file type,
single link and exact independently expected length with `fstat` before body
reads. It reads at most 256 KiB per chunk and one extra byte to check EOF, then
reuses the complete public payload decoder/binding checks. Device/inode, mode,
link count, size, mtime/ctime, path and directory observations remain stable
through read and decode. These are sequential observations, not an atomic
ancestry or multi-file filesystem snapshot; retain the caller's cooperative
source lease and original resource/custody owner for the complete operation.

The writer creates one new mode-0600 file with `O_EXCL`, without overwrite,
automatic parent creation or replacement. It keeps the creation descriptor
open through complete bounded writes, file `fsync`, parent-directory `fsync`
and readback bound to the original creation inode. The complete public loader
checks readback again, exact stored bytes must match, and closing descriptor,
path, link-count and directory checks must pass before a pin copy is returned.
Existing files, symlinks, hardlinks, nonregular files, bad sizes/pins, changed
identities, incomplete/failed writes and failed sync/readback refuse success.

Failures leave any created partial/complete file in place for the caller's
original custody; no deletion or rename is attempted. A failed sync does not
establish durability, even if readable bytes remain. A retry needs an explicitly
selected fresh destination. External replacement/unlink cannot be prevented by
sequential observations. This API performs no atomic publication or manifest
attachment and does not copy the separately required physical source files.

The independent wire/file ceiling stays 64 MiB, lowerable by exact positive
integer `max_bytes`. Existing 48 MiB expanded-input, depth/node/key and eight-MiB
generated-project/one-MiB manifest bounds remain unchanged. A replay file is
separate from the closed generated-project file population. File-byte bounds
do not bound total Python replay memory. Owner source changes produce new
producer pins/preparation generations despite unchanged typed commitments;
earlier Lean/cache receipts remain historical, without new compilation or old
native-artifact reuse qualification from this file cohort.

The [separate closed file qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-replay-files-20261020-03/qualification-summary.json) records
**25/25 passed** selected controls with exact qualified source
installation and retry03's original source/native/storage closeout. The selected
subset has 23 new file controls and two earlier byte regressions. The later
[explicit physical-fixture qualification](../../../../../workspace/test-logs/federal-corpus-audits/legal-ir-physical-validation-profile-20261021-01/qualification-summary.json)
now passes all six originally excluded public cases: unsafe-leaf read/write
symlinks and FIFOs, plus both symlink-parent cases. Their complete source and
the shared product owner remain unchanged. The existing validation resource,
pytest and launcher owners add a closed opt-in V2 request with exact declared
slots, owner-created private case directories, nofollow live byte accounting
and V2-only productive-child umask 077. All special fixtures must be cleaned up
by their original tests before strict final sealing. Policy, budgets, global
capacity and native custody checks remain unchanged.

The owner qualification comprises separate 92-case contract, 15-case physical
and seven-case focused regression cohorts; the seven repeat existing selected
cases. Every successful cohort closed its original source/native/storage owners.
The first V2 physical attempt correctly refused an inherited mode 0775 directory,
remains unqualified, and retains its failure evidence; its 96 MiB promise was
released through the existing recovery API with all ten files retained. The
earlier 25 and later six qualifications are separate source-pinned populations,
not one fresh 31-case run. Fictional sources
and generated test credentials retain their limits. The earlier 61-case bytes
cohort kept payloads in memory and retains that scope; this file API's separate
fixture qualification does not turn that historical cohort into a durable
production corpus delivery. No Hub publication, physical-source retention or
relocation, current-trust decision, Lean build, model/training, statutory fidelity,
source-to-model equivalence or convergence result follows. These remaining
deliveries stay in the existing task records.

The [earlier phase01 admission failure](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-replay-files-20261020-01/failed-controller-abnormal-close-01.json)
ran zero tests. Its exact controller was closed abnormally; no normal original
source READ or storage-release receipt is claimed for that failed attempt.
The original 96 MiB claim was fully charged in `reserved` status at retry03
qualification. The later [storage-only reconciliation](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-replay-files-20261020-01/reserved-recovery-candidate-v01/operational-closeout-v01/operational-summary-v01.json)
reuses the original already closed release through the existing
`reconcile_empty_unopened_validation_reservation_v1` owner, followed by an
actual postwrite census and the original recovery operation's source READ closure.
General [validation/recovery constraints](../../../../../docs/autoencoders/validation_storage.md)
remain with the resource owner. This does not reconstruct a normal phase01 source/native
closeout or qualify extra tests. The immutable retry03 qualification and
earlier failed-attempt records retain their original storage snapshots.
Retry02 was interrupted by the original strict live census detecting
its physical write-symlink fixture. Eight progress marks are not passed-case or
JUnit qualification; its completed case count remains unknown. Its actual
cleanup/storage recovery disposition is retained in the final qualification's
`prior_failed_attempts` metadata, without assuming recovery or test success.
The passing test/closure claims above apply only to retry03 and did not
themselves reconcile phase01 or turn either earlier failure into passing
test evidence. The later storage-only reconciliation adds no test passes.

### Qualification and remaining execution

The [main qualification record](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-preparation-20261020-01/qualification-summary.json) is **28/28 passed**: 28 cases, comprising 21 new preparation controls and seven existing regressions (four legacy, two parent and one official). The separate [physical-source closeout qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-physical-close-20261020-01/qualification-summary.json) supplies two independently qualified prepare/validate mutation-refusal cases on the same executing shared-owner and test source. Those two cases are reused without rerunning them; they do not cover a separate late-transport load/write race or an atomic filesystem snapshot. The cohorts qualify bounded preparation and transport engineering, with no model, training, aggregate Lean build, parent incremental cache or statutory-meaning result.

### Separate aggregate native execution

The [new aggregate native record](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-native-20261020-01/qualification-summary.json) is separate from the preparation cohorts above: **16/16 passed** for 16 main controls (11 new simulated/early and five existing regressions), plus **2/2 passed** for two actual authored FOL/TDFOL builds. Each actual project shares one donor across two physically distinct consumers, with 9 modules, 15 executed inputs and 6 unique conditional theorem observations; neither capacity for eight components nor statutory correctness is qualified. Complete child intakes, pending review, explicit premises and repeated contributor ordinals remain intact. The [native API guide](legal_corpus_definition_use_native_v2.md#literal-parent-shared-conditional-native-profile) explains the distinct receipt and limits. The separate [parent incremental installed-Lean qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-native-20261020-01/qualification-summary.json) is **2/2 passed** for two authored FOL/TDFOL cold/warm/affected/clean cases: 13 cold/0 warm/6 affected +7 reused/13 clean direct module calls per family, with real original source/review replay and exact affected/clean artifacts. This changes an unreviewed donor interpretation on unchanged physical text; the copied-text reusable custody branch is not independent statutory evidence. The preparation and aggregate-native cohorts above keep their own counts and profiles. Those positive cohorts do not by themselves qualify review/revocation or closing physical-mutation refusals. The [separate incremental qualification](legal_corpus_incremental.md#installed-lean-warm-refusal-qualification) qualifies those two negative paths on actual cold artifacts within its stated scope. Broader native invalidation, new modal/norm semantics, statutory admission and model/training improvement remain open.

### Same-operation replay cost

A source-only follow-up identified repeated parent replay in corpus_definition_use_review_v2, corpus_definition_review_v2 and legal_statutory_context_v2: endpoint definition and per-occurrence context validation repeatedly call legal_semantic_graph.bind_parent_source_occurrence, rebuilding the same parent corpus. Text-view, cache-occurrence, sentence-candidate and lineage checks in turn reopen selected parent rows and hash the complete independently pinned file. This is call-graph analysis, not measured timing attribution. Investigate bounded same-operation reuse in the existing binding/parent owners, preserving full population/input commitments, source/FD/path/producer-change checks, current review/revocation replay and final physical fences. Do not replace these with a persistent trust cache or remove closing checks to shorten qualification.
