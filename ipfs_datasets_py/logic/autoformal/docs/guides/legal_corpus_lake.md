# Graph-bound definition/norm Lean preparation

`logic/autoformal/legal_corpus_lake.py` assembles a local candidate Lean project
from independently bound `corpus_definition_norm_adapter` records. It delegates
semantic lowering and project generation to the unchanged
`legal_source_definition_norm_lake` owner. Preparation and file verification
execute no Lean compiler, model, provider, optimizer or native backend.

The supported profile is
`independently-bound-section-local-joint-modules/v1`: one joint definition and
universally guarded unary norm per generated module. Both supported native
families retain their original full AST and parameterized interpretation.
The generated `formula_0` is a `Nat → Prop` representation with arbitrary
entity/predicate/modal interpretations, rather than a discharged theorem.

## Independent input population

`prepare_definition_norm_corpus(candidate_inputs, *, expected_population,
toolchain)` accepts one through 64 ordered inputs. Each input is a closed
dictionary containing the exact bytes `candidate_raw`, `report_raw`,
`request_raw` and `raw_html`. The separately supplied ordered population has
these closed fields for every input:

| Pin | Meaning |
| --- | --- |
| `candidate_sha256` | Exact original candidate file bytes |
| `candidate_cid` | Expected sealed candidate record identity |
| `graph_cid` | Expected complete candidate graph identity |
| `request_sha256` | Exact original request file bytes |
| `report_sha256` | Exact original native report file bytes |
| `raw_sha256` | Exact raw HTML bytes |
| `extracted_sha256` | Complete normalized document view bytes |

These expectations must come from trusted intake, outside the incoming files.
Self-consistent hashes supplied by the same untrusted producer establish only
internal consistency. The preparer strictly parses the input files, regenerates
the complete source/definition/norm candidate, compares graph and candidate
identities, and then delegates the whole ordered request population.

Duplicate candidate/graph CIDs are refused. The unchanged native owner also
refuses duplicate `(norm_id, family)` identities, including collisions between
otherwise distinct document versions. This profile does not rename caller
identities or silently partition or discard colliding records. Broader corpus
namespacing requires its own explicit versioned contract.

The complete input population is bounded to eight MiB before semantic
regeneration. Individual JSON files retain the common one-MiB record bounds;
raw HTML retains the source adapter's separate bounds. The native project has
an eight-MiB bound, while its sealed corpus manifest retains the common one-MiB,
depth and node limits. Exceeding any bound refuses the complete preparation.
These limits do not imply that every 64-record population fits.

## Source, graph and module custody

The immutable `CorpusPreparation` contains canonical `manifest_json` and the
native owner's exact sorted file tuples. Its manifest preserves:

- The entire ordered independently pinned population and its content identity.
- Candidate, graph, source version, definition, norm, term, scope, symbol and
  joint AST record CIDs for each module.
- Exact graph assertion node CIDs, semantic node/content identities and
  `DEFINES`/`USES_DEFINITION` edge identities and endpoints.
- Every ordered source binding role, occurrence identity, paragraph population,
  Unicode character interval and UTF8 byte interval.
- Each joint module path, exact generated file hash and qualified `formula_0`
  declaration, including Prelude and root in expected module coverage.
- The unchanged native preparation manifest and all its producer pins, plus
  separately hashed corpus orchestration, adapter and contract source owners.
- Every native project file: Lake configuration, pinned toolchain, shared
  Prelude, root imports, each joint module and `definition-inputs.json`.

Original file SHA256 pins and the existing owner's canonical request/report
SHA256 pins have distinct recipes. Neither replaces the other. Candidate and
source companions remain external replay inputs; the generated project is not
a standalone archival copy of every original artifact.

`validate_definition_norm_corpus` rebuilds the complete typed preparation from
the externally supplied original inputs, ordered pins and toolchain. A resealed
manifest, rewritten module, changed toolchain, dropped row or swapped source
cannot substitute for that independent regeneration. Producer pins preserve
the native owners' existing absolute-path limitation: reports prepared in a
different source tree may refuse even when source file bodies are identical.

## Local project output

`write_definition_norm_corpus` requires a new directory. It validates the full
preparation before writing, exclusively creates and flushes every native file,
performs exact readback, and writes `corpus-manifest.json` last. It then performs
complete manifest-pinned readback. A failure can leave an incomplete owned
directory; a directory's existence is not a completion receipt. No existing
project is overwritten and no remote release pointer is changed.

`load_definition_norm_corpus` requires the expected manifest SHA256 and all
independent preparation inputs. It checks the exact closed file/directory
population, refuses symlinks and nonregular files, bounds complete reads and
regenerates every expected byte. The manifest's `file_sha256` covers native
project files; its own exact bytes are pinned externally to avoid a self-hash.

## Remaining corpus work

All source authenticity, source meaning, context closure, review, admission,
training, compilation and proof authority flags remain false. This profile
does not infer legal meaning, resolve cross-section definitions, deduplicate
shared definitions into separately imported modules, or establish a reviewed
statutory corpus. Shared definition generation, dependency partitioning,
actual pinned builds, composition obligations and incremental invalidation
remain downstream milestones. An actual build must consume the exact bound
project and verify complete module coverage through the existing native gates.

The additive [shared-definition profile](legal_corpus_shared_lake.md) supplies
the next narrow preparation/build path. It preserves this joint-module profile
and its original input and native identity restrictions.
