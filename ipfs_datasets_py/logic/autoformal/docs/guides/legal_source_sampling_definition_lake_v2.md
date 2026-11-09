# Native Lean builds for sampled-source V2 definitions

[`legal_source_sampling_definition_lake_v2.py`](../../legal_source_sampling_definition_lake_v2.py)
prepares and compiles one exact
[sampled-source definition binding](legal_source_sampling_definition_binding_v2.md).
It preserves the original source/review/compiler/candidate owners and adds a
separate native compilation receipt. The original binding, candidate and whole
review population retain their existing authority flags and zero gold masks.

The supported interpretation is the existing caller-declared unary definition
profile: `forall x, head(x) iff body(x)`, with a bounded Boolean body, through
`fol` or `tdfol`. Use a separate project for each binding and family. This
adapter does not translate V2 source records into the legacy V1 definition or
definition-plus-norm profile.

## Inputs and public API

Retain the complete original binding envelope, original request JSON bytes,
complete review bundle, ordered supplied responses, original HTML and acquisition
descriptor. The bundle retains the complete sampler report and unselected
source/context population. Obtain expected commitments independently of later
incoming artifacts.

```python
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_lake_v2 as lake,
)

replay = dict(
    expected_request_sha256=original_request_file_sha256,
    expected_bundle_sha256=complete_bundle_canonical_sha256,
    expected_response_sha256s=ordered_response_canonical_sha256s,
    expected_sampling_report_sha256=complete_sampler_canonical_sha256,
    descriptor=original_acquisition_descriptor,
    expected_descriptor_sha256=descriptor_canonical_sha256,
    expected_raw_sha256=original_html_sha256,
    expected_raw_bytes=original_html_length,
)

preparation = lake.prepare_definition_lake_v2(
    result, request_raw, bundle, responses, raw_html,
    expected_binding_sha256=independent_complete_binding_sha256,
    toolchain="leanprover/lean4:v4.26.0",
    **replay,
)
# Retain this commitment independently before accepting a later preparation.
expected_preparation_sha256 = lake.preparation_sha256(preparation)
lake.validate_definition_lake_v2(
    preparation, result, request_raw, bundle, responses, raw_html,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_binding_sha256=independent_complete_binding_sha256,
    toolchain="leanprover/lean4:v4.26.0",
    **replay,
)

# Invoke inside the established owned validation resource context.
receipt = lake.build_definition_lake_v2(
    preparation, result, request_raw, bundle, responses, raw_html,
    expected_preparation_sha256=expected_preparation_sha256,
    expected_binding_sha256=independent_complete_binding_sha256,
    toolchain="leanprover/lean4:v4.26.0",
    lake_executable=explicit_installed_native_lake_path,
    output_directory=fresh_output_directory,
    timeout_seconds=60,
    cancellation=cancellation_signal,
    **replay,
)
receipt_sha256 = lake.compilation_receipt_sha256(receipt)
```

The immutable `DefinitionLakePreparation` contains `manifest_json` and an exact
sorted tuple of `(relative_path, UTF8_text)` files. `preparation_sha256` commits
the full canonical `{"manifest": manifest, "files": [[path, text], ...]}`
envelope. This differs from the manifest file hash, its record CID, the binding's
full canonical hash and the original request file hash. Receipt hashing also
commits the full canonical record. Hashes provide integrity under the caller's
chosen input custody; hashing an incoming artifact alone establishes no trust.

Only the original binding replay arguments are accepted, with optional
`view_limits` and `sampling_limits`. Unexpected arguments refuse. The public
source/review owners retain their own bounds and schema validation.

## Lazy preparation and complete replay

Public import loads only the standard library. Preparation first bounds finite
ordinary JSON, duplicate-free request bytes, source bytes, ordered response
populations and all independent commitments. It then invokes the existing public
`validate_definition_binding_v2` owner to regenerate the complete source bundle,
responses, definition report, candidate and population. No review prose becomes
an AST, and missing declarations remain pending.

After that replay, the existing native fragment owner independently reparses and
renders the exact native AST. Its complete fragment and Lean body must equal the
original report. Preparation uses the existing prelude and that unchanged body;
it adds only the fixed module/import wrappers and project metadata. Producer
files are pinned and checked before and after preparation.

Validation checks the independently expected whole preparation commitment and
regenerates every manifest field and file. Resealing a changed AST digest,
authority flag, source role, population commitment, module/import population or
Lean body cannot replace this replay.

## Six project files and three modules

Each preparation has exactly these six files:

| File | Contents |
| --- | --- |
| `lakefile.toml` | One Lean library named `legal`, rooted at `LegalSourceDefinitionV2` |
| `lean-toolchain` | Explicit version-pinned Lean toolchain |
| `v2-input-bindings.json` | Exact original binding metadata in canonical JSON |
| `LegalSourceDefinitionV2/Prelude.lean` | Existing parameterized interpretation prelude |
| `LegalSourceDefinitionV2/Definition<sha256>.lean` | Exact existing native declaration, importing the prelude |
| `LegalSourceDefinitionV2.lean` | Root import of the one definition module |

The definition module name derives from the complete binding commitment and
family. The manifest's ordered `expected_modules` contains the prelude,
definition and root. Its exact `module_imports` graph is closed and acyclic;
`file_sha256` commits every generated byte. The manifest also retains exact
source-binding metadata, candidate/population commitments, review status, native
AST/fragment/body hashes and producer pins. It contains no complete HTML or
review bundle: those remain separately retained replay inputs.

## Native execution and retained observations

`build_definition_lake_v2` requires a fresh, nonexistent output directory and an
explicit installed native Lake ELF executable with an installed sibling Lean
ELF executable. The existing toolchain owner checks both versions and records
binary hashes. The adapter performs no installation or download. It executes:

```text
<verified-native-lake> --offline --no-cache build legal
```

The shared bounded process runner receives all six exact input files, the three
expected `.olean` paths and the six input paths for post-execution readback.
Success requires the exact command, native runtime and positive actual PID,
complete nonempty compiled-module coverage, unchanged executed input bytes,
unchanged compiler binaries, successful post-run preparation/binding replay,
and no timeout, cancellation, truncation, workspace exhaustion or runner error.

Compilation opts into `owned_process_observation=True`. Its typed native
lifecycle observation must match the returned leader PID and confirm cleanup:
leader reaped, complete sampled descendant/group tracking, no remaining children,
joined pipe workers and removed workspace. `workspace_cleaned` must also hold.
`process_tree_terminated` records a forced intervention; it can be false after a
clean normal exit. These observations provide sampled process ownership, not
kernel containment or a guarantee against an escaped process between samples.

The caller acquires and retains the existing
[owned validation resources](../../../../../docs/autoencoders/validation_storage.md). Internal limits include a
finite compiler timeout in `(0, 60]` seconds, corresponding CPU bound, a sampled
2 GiB process-tree RSS guard and a 128 MiB workspace bound. Capture bounds are
2 MiB per stream/output file. JSON, source and project bounds refuse rather than
truncate their population: one MiB per request/companion/manifest/receipt,
four MiB per binding envelope, 64 MiB per bundle or aggregate response input,
8,192 responses, 8,000,000 raw HTML bytes and eight MiB per complete project.

A returned build observation retains twenty regular files when all expected
artifacts and inputs are present:

- `project/`: the six frozen files plus `corpus-manifest.json`;
- `compiled/`: the three actual `.olean` files;
- `executed-inputs/`: the six input bodies read back from the compiler workspace;
- `stdout.txt`, `stderr.txt` and `runner-error.txt`: complete bounded captured
  text, with independent `log_sha256` and `log_bytes` receipt entries;
- `build-receipt.json`: the separate sealed compilation observation.

The receipt contains at most 32 KiB source-byte previews per captured text and
an explicit `receipt_text_truncated` flag. Full retained captures remain
available; malformed UTF8 replacement can increase their encoded size. Receipt
artifact maps contain only the three compiled modules. Executed source hashes
and readback status remain separate. Missing artifacts, changed executed sources
and unsuccessful returned observations are retained as failures.

An `OwnedToolCleanupError` preserves the unqualified frozen project/refusal and
re-raises the **same exception with its actual cleanup handle**. Serialization
cannot replace that owner. The caller must retain its resource custody until
the handle confirms cleanup. Input, commitment or installed-toolchain refusals
raise before the compilation command runs.

## Meaning, proof and admission boundaries

A successful receipt can set its own `backend_executed` and
`lean_compilation_verified` observations. It leaves the original binding,
candidate, review population and their flags byte-identical. All legal review,
source authenticity, governing applicability, semantic admission, model and
training/gold qualifications remain false, with integer-zero masks.

These modules contain parameterized declarations. They produce no theorem:
`proof_checked`, `kernel_proofs_checked` and
`translation_preservation_proved` remain false. Native AST replay and successful
Lean compilation do not establish a theorem connecting a separately defined
serialized-AST denotation to the generated expression. That translation
preservation work remains distinct from reviewed correspondence to legislation.

For example, the body “a person in an enlisted grade” may remain one opaque unary
predicate. Compilation does not recover person/grade sorts or membership
relations. A retained “in this title” scope declaration does not formalize title
hierarchy or prove governing legal applicability. General definitions, norms,
aliases, ground entities, external definition resolution and definition-use
composition require their own supported profiles and reviewed dependencies.
See [V2 source definitions](legal_source_definition_v2.md) and
[V2 definition review](corpus_definition_review_v2.md).

## Qualification status

The October 15 owned qualification passed **207 tests with no failures, errors or
skips**: 169 new adapter cases, seven V1 definition build regressions and 31
shared-corpus regressions. The
[test source](../../../../../tests/unit/logic/autoformal/test_legal_source_sampling_definition_lake_v2.py)
exercises real preparation/replay and explicitly synthetic process-boundary
controls. Its test doubles do not establish a native Lean build. The
[test receipt](../../../../../../../artifacts/legal-ir-definition-lake-v2-20261015-01/test-receipt.json)
records the suite counts, resource release and evidence hashes.

Actual two-family native qualification **passed** using installed Lean 4.26.0.
The separately retained
[actual-source driver](../../../../../../../artifacts/legal-ir-definition-lake-v2-20261015-01/run_actual_definition_lake.py)
and
[request reference](../../../../../../../artifacts/legal-ir-definition-lake-v2-20261015-01/actual-source-request-reference.json)
bind the exact inputs and execution. Ten driver checks include two pure
preparation refusals. Two successful native projects produced all six expected
modules, retaining exact executed inputs and confirmed sampled cleanup. A
separate deliberately invalid nonfirst definition module produced a Lean type
mismatch after compiling only the prelude. Its failed receipt and seventeen
files remain separate from the two successful compilation receipts. Three
build commands and four installed-version probes ran in total.

The [independent readback](../../../../../../../artifacts/legal-ir-definition-lake-v2-20261015-01/independent-actual-native-readback.json)
passed nine checks over all seventy-two files (7,111,225 bytes), 35 producer
files, both installed binary pins, 2,413 CID seals, 1,138 all-false authority
objects and 2,264 strict integer-zero masks. It checked recorded sampled cleanup
observations without rerunning the producers or claiming retrospective kernel
containment. Both validation resource reservations were durably released.

These two family routes represent **one** physical, unreviewed §101 definition.
Both retain all 560 pending subjects and zero actual responses/reviews. The
[qualification receipt](../../../../../../../artifacts/legal-ir-definition-lake-v2-20261015-01/qualification-receipt.json)
records native compilation only. Source-preservation proofs, legal review,
definition-use bindings, training, model convergence and corpus admission remain
separate gates.
