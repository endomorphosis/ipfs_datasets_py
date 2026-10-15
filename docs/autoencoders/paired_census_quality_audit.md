# Auditing paired census outputs and deferred goals

Run `scripts/ops/legal_ir/audit_paired_census_quality.py` to inspect a bounded
selection of local paired census bundles. It calls the existing
`paired_span_census.load_paired_census_bundle` reader, which verifies manifest and
table hashes, schema, comparison consistency, artifact references, portable
goal bindings, and the absence of admission authority. It does not download,
compile, run a model, open a database, enqueue goals, or update source bundles.

```bash
python3 -B scripts/ops/legal_ir/audit_paired_census_quality.py \
  --manifest /local/repository-layout/autoformal/uscode/paired-v2/manifests/AGENT/manifest-HASH.json \
  --manifest /another/local/manifest-HASH.json \
  --output /absolute/path/to/new-quality-audit.json
```

Keep repository-layout downloads intact, or place a manifest beside its three
table files. Both layouts are handled by the existing reader. Use
`--workspace-tree /home/barberb/lift_coding/external/ipfs_datasets` when running a
candidate script from outside its normal repository location. A process that
already imported the editable HACC tree is rejected. The normal logic-tree guard
still verifies the compiler, decompiler, and parser origins; importing these
modules does not execute a compilation.

The defaults and fixed ceilings are 16 explicitly selected manifests, 64 MiB of
aggregate compressed table bytes plus manifest bytes, and 64 span rows per
bundle. Flags can reduce these bounds. Header preflight rejects an excessive
selection before loading any bundle. The existing reader separately enforces
the same byte ceiling on each bundle's decoded Arrow data and artifacts. It
processes bundles sequentially. Repeated inode aliases and copied manifests
with identical content hashes are rejected rather than counted twice.

Two additional fixed 64 MiB bounds apply to the retained row/goal compact JSON
and the final indented UTF-8 report including its trailing newline. The retained
record charge conservatively includes a small JSON wrapper for every bundle.
The audit checks that charge before appending each bundle's records and checks
the complete output before creating the report file. Exceeding a bound aborts;
it never truncates evidence or emits a filtered partial report. These are
userspace input/allocation/output guards, not an operating-system quota or a
hard guarantee that process RSS is below 64 MiB.

## Three different formal-output streams

The report groups outputs by `stream`, `origin`, `format`, `family`, and
`syntax_status`. These groups must remain distinct:

| Stream | Retained field | Interpretation |
| --- | --- | --- |
| `canonical_compiler` | `compiler.canonical_formal_outputs` | Serialized canonical typed rules; inspect producer status and complete rule fields separately. |
| `compiler_view` | `compiler.formal_outputs` | Deterministic compiler/source-codec views, including modal ASTs and fallback frames. |
| `autoencoder` | `autoencoder.formal_outputs` | Model-side output with its recorded origin; a guided compiler path is distinct from an independent learned decoder. |

A formula-shaped modal AST or fallback frame can exist while the canonical
typed compiler abstains. Conversely, a canonical typed rule can exist when both
arrays used by the retained comparison are empty. The audit reports
`canonical_output_comparison_unavailable` for that case and preserves the
original comparison unchanged. The comparison concerns
`compiler.formal_outputs`, not the separately retained canonical array.

`producer_canonical_complete`, `producer_compiler_complete`, and
`producer_roundtrip_ok` are copied producer flags. They are not verified
semantic-coverage judgments. `canonical_compiled_rows` counts the stored
`compiled` status; it does not count Lean admissions. Reading a serialized rule
also does not prove that every enumerated object, recipient, exception, temporal
condition, or linked definition was preserved.

Agreement is counted separately for independent and diagnostic comparable rows.
Guided compiler agreement remains diagnostic. Raw vectors, target-conditioned
projection cosine, and reconstruction losses are not independent formula
decoding. Inspect `learned_formula_capture_verified`, source binding, origin,
target conditioning, and syntax status in the original evidence rather than
inferring them from a favorable score.

## Sidecar review hypotheses

The audit flags narrowly recognizable publisher footers, notes headings, and
unfinished public-law citation fragments. It also flags an enumerated `(A)` /
`(B)` source whose short serialized typed object starts with a recipient and
lacks enumeration or clause-separator markers, so reviewers can check
enumeration coverage across the complete rule. These are hypotheses
for source and neighboring-span review, not proven non-operative
classifications or definitive compiler failures. Notes can contain effective
dates and other legally significant language.

Every flag sets `requires_context_review=true` and `classification_proven=false`.
No row or goal is dropped, rewritten, reprioritized, or marked resolved. Original
goal IDs, issue labels, source and observation links, packet/task artifact hashes,
and enqueue status remain intact. A later review can propose a separate,
evidence-backed classification or context-retrieval goal without silently
changing this census.

Each report row retains complete source text, all three formal-output arrays,
decompiled text, producer flags and provenance, goal links, manifest hash, and
source/component artifact references. Fallback metadata cues are copied from
AST metadata without turning them into supported semantics. Original bundles
and their full artifact payloads, vectors, and producer receipt remain the
source of truth; the report is an additional sidecar rather than a replacement.

The audit covers selected retained observations only. It establishes no corpus
coverage estimate, inference speedup, new training convergence, semantic
qualification, or independent-decoder fidelity. `admitted`, `Lean_admitted`,
`formalized`, and `enqueued` remain false. Only `lake build <Lib>` can establish
Lean admission. The Constitution remains unformalized.
