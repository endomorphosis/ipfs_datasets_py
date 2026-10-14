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
