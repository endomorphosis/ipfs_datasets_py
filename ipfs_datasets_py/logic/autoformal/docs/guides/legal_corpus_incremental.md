# Incremental compilation of shared legal corpus modules

`logic.autoformal.legal_corpus_incremental.build_incremental_shared_corpus`
connects the [shared-definition corpus](legal_corpus_shared_lake.md) to the
existing LegalIR incremental compiler. Every current candidate and its source,
graph, definition binding and generated module is independently regenerated.
Only exact native compiler artifacts can be reused. Public import initializes
no compiler, session or numerical model.

## Execution and cache identity

The bounded `verified-legacy-olean-per-module/v1` profile compiles generated
legacy Lean modules directly with the explicit installed Lean executable:

```text
lean -o compiled/LegalCorpus/Norm….olean LegalCorpus/Norm….lean
```

Every module runs in its own bounded private workspace. `LEAN_PATH=compiled`
contains only its verified transitive generated imports; implicit imports come
from the pinned installed toolchain. Relative source/output paths make artifact
identity independent of the temporary directory. This profile reuses `.olean`
artifacts and provides no Lake trace/cache reuse or newer `module`-header support.

The sealed execution contract binds the declared Lean version, exact installed
Lean/Lake binaries and version probes, all implementation owners, platform,
command/environment and the complete selected installed library population.
The library closure includes `.olean`, `.olean.server`, `.olean.private`, `.ir`,
`.ir.sig` and shared libraries, including implicit `Init`. It is streamed both
before and after execution under the caller's existing validation lease. The
manifest limit is 16,384 files, three GiB of library bytes and four MiB of JSONL;
an unsupported population refuses without truncation. This is local content
integrity, with no upstream release-signature authentication claim.

## Calling and retaining a build

Supply the current immutable preparation, exact `candidate_inputs`, independently
pinned `expected_population`, `toolchain`, explicit `lake_executable` and a fresh
`output_directory`. The whole build has a maximum 60-second deadline, including
regeneration, bounded version probes, closure hashing and native compilation.
The common native runner uses one Lean thread, two GiB sampled tree RSS and a
128-MiB private workspace. A cancellation object may expose `is_cancelled()` or
`is_set()`, or be callable. The caller retains responsibility for the existing
shared resource lease and its cancellation signal.

For reuse, provide all three together:

- `previous_cache_raw`: exact saved `cache.json` bytes;
- `expected_previous_cache_sha256`: independently retained digest of those bytes;
- `previous_artifacts`: complete prior module-name-to-artifact-bytes mapping.

The cache has a closed schema and must be technically qualified. Exact original
source, recipes, direct import artifact hashes, generated theorem declarations,
all artifact hashes/sizes and the complete artifact root are revalidated before
reconstructing the previous compiler snapshot. It accepts no caller-fabricated
framework snapshot. Artifacts are bounded to four MiB each and 32 MiB total.

Each pass declares its module recipe and actual import dependencies. Stable
role tiers avoid invalidating an unrelated module when content-derived names
change their sort position. Changed definitions rebuild their users and root;
unrelated definitions remain reusable. Compiler/library/implementation changes
invalidate all artifacts. The existing incremental compiler additionally checks
current input and specification digests and the cached output digest. Failed
passes clear prior outputs, block descendants once and allow independent work
to finish.

## Evidence and qualification

Successful compilation requires an actual bounded native invocation for every
fresh module, exact command and output coverage, unchanged owners/toolchain,
exact current import artifacts and empty printed axiom-dependency lists for all
generated conditional theorems. The original theorem still requires the supplied
definition, norm and body hypotheses; it establishes no statutory fact.

The fresh output retains `project/`, compiled artifacts, `cache.json`,
`toolchain-closure.jsonl`, `module-executions.jsonl` and `build-receipt.json`.
Cache bytes and execution-observation bytes are hash-bound in the sealed receipt.
Evidence is written exclusively and read back before publishing that receipt.
Failed native runs retain a false-qualified receipt and available independent
artifacts; they cannot become a reusable qualified cache.

Receipts separate `compiled_modules` from `reused_modules` and `fresh_theorems`
from `reused_theorems`. A warm build has zero module compiler invocations and
`backend_executed=false`; installed-version probes are reported separately.
Framework speedup fields are estimates. Use the retained phase wall times and
actual native invocation counts for measured comparisons.

Source authenticity, reviewed source meaning, governing-context closure,
statutory admission, training qualification and legal proof authority remain
false. Reviewed cross-section resolution, negative lookup dependencies,
authenticated release publication and a connected statutory pilot remain open.

## Parent shared definition-use profile

`build_incremental_parent_shared_corpus_v1` extends this same implementation owner
and pass manager for an already prepared `LegalCorpusParent` aggregate. It uses
the separate `verified-parent-source-bound-olean-per-module/v1` profile. Legacy
preparations, caches and aggregate Lake outputs cannot seed this direct-Lean
cache. The existing [parent aggregate native profile](legal_corpus_definition_use_native_v2.md#literal-parent-shared-conditional-native-profile)
remains a separate qualification.

The parent schemas are:

| Record | Schema |
| --- | --- |
| Cache | `legal-corpus-parent-direct-lean-cache/v1` |
| Execution contract | `legal-corpus-parent-direct-lean-execution-contract/v1` |
| Build receipt | `legal-corpus-parent-incremental-native-build/v1` |

Call the parent API with the original component inputs and independent complete
preparation pin, rather than the legacy `candidate_inputs`:

```python
receipt = build_incremental_parent_shared_corpus_v1(
    preparation,
    component_inputs=component_inputs,
    expected_population=expected_population,
    expected_preparation_sha256=expected_preparation_sha256,
    toolchain=toolchain,
    lake_executable=lake_executable,
    output_directory=fresh_output_directory,
    timeout_seconds=60,
    operation_timeout_seconds=3600,
)
```

Derive and retain `expected_preparation_sha256` using the existing native owner's
`parent_shared_preparation_sha256`. For a subsequent run, supply the same three
previous-cache arguments described above, with their independent digest and the
complete prior artifact bytes. The parent cache is refused before compiler
probes if its profile, closed records, artifact population or evidence differs.

### Current source custody and dependency invalidation

Opening validation delegates to
`validate_parent_shared_definition_use_native_v1` with every original component,
ordered population, toolchain and complete preparation pin. The coordinator then
creates a private typed copy of the validated preparation and independently
checks the whole pin against both that copy and the original caller object.
Compilation and retained project files use this frozen copy. Closing validation
replays the **original caller preparation and original inputs** and must reproduce
the exact frozen project. A warm cache cannot bypass current physical source,
review, scope, edition or dependency validation. A failed closing replay cannot
replace retained executed source with a caller's changed source.

The actual closed import DAG determines pass dependencies and stable graph
depths; source-name sorting or contributor ordinals do not determine reuse:

| Module role | Required generated imports |
| --- | --- |
| Prelude | None |
| Definition | Prelude |
| Alias | Exact donor and consumer definitions |
| Joint | The same donor, consumer and alias |
| Root | Every unique Joint |

There are at most 34 modules, all reachable from `LegalCorpusParent`. Recipes
bind exact source, ordered imports, content-derived module identity and the
execution contract. Definition provenance uses the complete retained original
endpoint identity and native fragment, excluding unrelated component assessments
and contribution ordinals. Alias provenance uses its retained binding, alias and
scope records; Joint provenance uses its component pin. Their sorted, distinct
retained input-binding file hashes commit the complete original component input
trees, including declared registry/query/lookup dependencies and searched empty,
unavailable or competing partitions. This binds the declared lookup population;
it does not establish an exhaustive legal inventory or governing scope.

A changed definition invalidates its dependent aliases, joints and root while
unrelated branches can reuse their verified artifacts. A changed lookup binding
can invalidate those users even when the generated Lean text is identical.
Compiler, installed-library or implementation-contract changes invalidate the
whole cache. The implementation pin scope is the existing native producer/owner
closure, this owner, and the five direct LegalIR compiler, pass manager,
obligations, schema-evolution and source-map owners. It is not a complete Python
environment attestation. Every current contributor and its review status,
original input commitment, theorem roster and explicit premises remains in the
receipt and frozen project.

### Native observations, bounds and reuse

Fresh parent module calls use the existing runner with
`owned_process_observation=True`, one Lean thread and verified transitive imports
in `LEAN_PATH=compiled`. Capture must cover exactly the new artifact, executed
source and every supplied transitive generated import artifact, with unchanged
input bytes. Acceptance requires the exact native command/runtime, a typed
sampled lifecycle, current observed process identities and confirmed cleanup.
The parent axiom check requires exactly the source-derived Alias theorem and two
Joint theorems; duplicates, unknown claims and stderr claims cannot establish
proof observations. Modules with no theorem declarations reject unexpected
axiom or `sorry` markers.

A previous cache revalidates the exact compiler path against its saved execution
contract, full artifact hashes, transitive input readback hashes, strict axiom
observations and historical lifecycle consistency. Historical identities are not
reinterpreted as current processes. Sampled lifecycle evidence does not attest
kernel containment. If the runner raises `OwnedToolCleanupError`, the exact
exception and cleanup handle survive the pass manager's diagnostic handling;
queued callbacks cannot dispatch another native command and no cache is
published. The caller retains ownership until the existing cleanup owner
confirms closure.

The parent compiler budget is at most 60 seconds cumulatively for probes,
library closure and module compilation, excluding synchronous full source/review
replays. The whole-operation default and maximum is 3,600 seconds, checked
cooperatively before and after replay and around publication. Replay is not
safely preempted inside these synchronous owners; the existing outer owned
resource timeout remains the hard boundary. The compiler runner retains the
legacy four-MiB per-artifact, 40-MiB input and 128-MiB workspace bounds. Parent
retained artifacts are capped at **nine MiB total**, matching the existing closed
transport; the legacy total remains **32 MiB**. Exact complete retained artifact
readback occurs before cache or receipt publication.

Parent receipts keep `compiled_modules`/`fresh_theorems` separate from
`reused_modules`/`reused_theorems`. A warm run may execute zero module compiles
while still performing both full public replays, version probes and closure
checks. Reused artifacts do not count as freshly executed proofs. Current review
outcomes and assumptions always come from the current validated preparation.
Source/legal/review/proof authority, admission, model and training claims remain
false.

### Parent qualification status

The [closed coordinator qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-20261020-01/qualification-summary.json)
passed **22/22 cases**: 20 new authored controls and two existing regressions.
Its public source/review replay, compiler artifacts, installed-library closure
and typed lifecycle observations are synthetic substitutes. The real DAG,
retained-record provenance, cache, pass manager and publication checks run.
The authored fixture records 13 cold module calls, zero warm calls, six affected
calls with seven reused modules, and 13 clean calls; affected artifacts equal the
clean result. Renamed content identities remove the old donor; changed negative
lookup bindings rebuild five users/root modules while retaining eight modules.
These are coordinator observations with fake compiler bytes. The original owner
recorded stopped observed processes, released native/storage custody and the
subsequent outer source READ release. No actual Lean or model execution occurred.

### Separate installed-Lean qualification

The [installed-Lean qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-native-20261020-01/qualification-summary.json) is **2/2 passed** for two separately enrolled authored FOL/TDFOL cases. This is a separate qualification from the 22 authored coordinator cases above and the aggregate native profile's 16 main controls and two Lake builds. Those earlier scopes are retained; they are not rerun or added to this case count.

Each case uses three component entries: two share one donor across two distinct physical consumers, and a third copied-text branch has separate engineering custody. That branch is not an independent statutory source or meaning decision. The changed donor supplies an explicitly different unreviewed `all`→`any` interpretation of unchanged physical text; it is not a source-text amendment. Both original consumer records and physical backing bytes remain unchanged.

The **2/2 passed** result retains four API build stages per family:

| Stage | Direct Lean module compiles | Reused modules | Fresh conditional theorem observations |
| --- | ---: | ---: | ---: |
| Cold | 13 | 0 | 9 |
| Warm | 0 | 13 | 0 |
| Affected | 6 | 7 | 6 |
| Clean | 13 | 0 | 9 |

Both affected Alias/Joint paths and the root rebuild; the obsolete donor module is absent, and the separate custody branch remains reusable. Affected artifact bytes and the artifact root equal the clean build exactly. Across both families, **2/2 passed** binds eight API build stages, 64 direct Lean module compiles and 16 version probes. These are direct compiler invocations, not eight Lake builds or eight independent examples. Every build stage retains the complete 13-module artifact population, full child provenance, pending review outcomes and explicit premises. Warm and affected reuse preserve historical theorem evidence without counting it as a new execution.

The **2/2 passed** qualification uses the genuine public parent source/review validator, installed Lean4.34.1 binaries, complete installed-library closure checks and original native runner. Its record binds the 193 source pins, both original request/results and durable source/native/storage closeout. Source/review replay and compiler observations are not substituted in these two cases. Cohort intervals overlap and inner compiler intervals are nested; they are not additive speedup evidence. No measured speedup is inferred from reducing compiler calls.

The **2/2 passed** cases supply positive source/review replay and one changed-interpretation invalidation edge only. They do not qualify real review/revocation refusals, closing physical-source mutation refusals, a changed source-text amendment, or new runtime negative-lookup/producer/toolchain changes. Existing authored negative and invalidation controls retain their synthetic scope. Physical closing replay remains sequential rather than an atomic multi-file snapshot. The supported FOL/TDFOL fragment remains bounded quantified unary Boolean definitions with assumed aliases; no new modal or norm-operator semantics is qualified. Source-to-model equivalence, competent source/edition/meaning/applicability review, statutory admission and model/training improvement remain open.

### Genuine-validator warm refusal qualification

The [closed mixed-process qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-genuine-refusals-20261020-01/qualification-summary.json)
passed **24/24 cases**: the earlier 22 coordinator/legacy regressions plus two new
controls. These are 24 selected cases, not 46 unique cases. Both new controls
use the genuine public parent source/review/preparation validators on fictional
authored Parquet sources and freshly generated test signing credentials. Their
baseline cache has one FOL component and six modules; compiler artifacts,
version probes, installed-library closure and lifecycle observations remain
**authored test substitutes**.

- A physical-source mutation immediately before warm closing validation rejects
  the build after a successful genuine opening replay, with zero fresh compiler
  calls. The failed build retains the original frozen project and artifact bytes;
  the changed physical bytes cannot replace the retained executed project.
- A genuinely re-signed registry revocation rejects an old assessment at warm
  opening before helper probes or compilation and publishes no build output.
  A fresh assessment confirms valid signatures and the explicit `key_revoked`
  refusal, distinguishing revocation from a corrupted-signature test.

The same process also reruns the earlier controls with the authored fixture's
producer/native pin fields drawn from the actual existing producer owners. This
makes its declared source scope compatible with the genuine preparation scope;
no production first-use guard is reset or weakened. The original 22-case receipt
and the separate two-case installed-Lean positive result retain their own scopes.
The closed record binds canonical installation of the exact qualified test bytes,
215 unchanged non-document source pins revalidated under exclusive WRITE, and
original source, native and storage closeout.

Reuse these genuine-validator refusal controls rather than scheduling them as
missing. They do **not** qualify an actual installed-Lean negative cache/artifact
profile. The separate installed-Lean refusal qualification below supplies that
bounded integration. New source-text/scope/lookup or producer/toolchain
invalidation and statutory source/meaning/applicability decisions still need
their own evidence. No source-to-model equivalence, training or convergence result
follows from this cohort.


### Installed-Lean warm refusal qualification

The [separate closed qualification](../../../../../workspace/test-logs/federal-corpus-audits/parent-shared-incremental-native-refusals-20261020-01/qualification-summary.json) passed **4/4 selected cases**:
the two existing genuine-validator regressions followed, in the same process,
by two new actual installed-Lean FOL/TDFOL cases. Each new case creates one
genuinely signed fictional component and a real six-module cold cache with
three empty-axiom conditional theorem observations. Across both new cases this
executes **12 native module compiles and eight actual version probes**. The
original positive four-stage and authored-compiler cohorts retain their own
counts and receipts; they were not rerun as new native cases.

A physical mutation immediately before genuine warm closing replay retains the
six original compiled artifacts, their exact historical execution evidence and
the frozen project, while marking the build/cache unqualified. Warm reuse makes
zero fresh compiler calls and three historical theorem references per family;
it still executes both genuine version probes. Original physical bytes are
restored before the next control. A freshly re-signed registry revocation then
rejects the retained old assessment at warm opening, before any runner/probe
call or output publication. Both controls keep the original qualified cold
cache unchanged. The deliberately failed closing cache is never a baseline.

The test runner observer forwards exact calls to the original native owner;
source/review validation, installed-library closure, probes, compiler outputs
and lifecycle observations are genuine. The module-cached authored setup now
restores fake process hooks before returning; function-scoped hooks serve only
the two existing regressions. The selected old-before-real order checks this
boundary. No production first-use guard is reset or weakened.

These checks qualify bounded cache/refusal engineering on fictional sources
and generated test credentials. They do not establish competent statutory
meaning/applicability review, source-to-model equivalence or model convergence.
Source-text/scope amendments, competing/negative lookup changes,
producer/toolchain/library invalidation and failed-compiler descendant behavior
remain separate actual-native qualifications. Physical closing replay remains
sequential, and supported logic remains the bounded unary Boolean FOL/TDFOL
fragment with explicit alias and interpretation assumptions.
