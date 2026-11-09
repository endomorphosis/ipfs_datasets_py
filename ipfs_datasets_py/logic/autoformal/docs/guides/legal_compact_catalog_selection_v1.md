# Catalog score selection v1

`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_selection_v1`
selects at most one next token from a complete caller-supplied vector of 537
finite scores. The public optional-catalog prefix owner supplies the allowed
IDs. The selected ID has the greatest allowed score, with lowest-token-ID ties.
No neural network, source encoder, training operation or external tool runs.

This is an additive source generation. It leaves the exact bytes of the existing
content selector, token owners, numerical head, generator, source-generation and
batch consumers unchanged. Those owners remain pinned to their existing
contracts; the new selector does not make them catalog-compatible.

## API and inputs

```python
select_compact_catalog_token_v1(
    logits, prefix_ids, context_raw, *,
    expected_context_sha256, codec, expected_codec_sha256,
)
```

`logits` is exactly 537 plain finite floats or plain integers with absolute value
at most `2**53 - 1`. Every score is checked, including entries forbidden by the
grammar. Booleans, tensor/array objects, NaN, infinity and partial score vectors
are refused. Integer/float identity and negative floating zero remain present
in the captured score evidence.

`prefix_ids` is a plain integer list of at most 512 IDs. Well-shaped out-of-range
IDs retain the grammar owner's rejection; malformed API types or overlong lists
raise. `context_raw` is exact UTF8 JSON bytes for the complete
`legal-relational-compact-catalog-context/v1` wrapper with its independent
SHA256. The full wrapper includes the fixed
`referenced_predicates_in_catalog_order/v1` policy and the complete validated
catalog. `codec` and its independent hash must match the new public catalog
codec exactly. The old content codec is not accepted despite the same ordered
537 token spellings.

There is no target formula, expected tree, identity sidecar, checkpoint or
source-permission input. This operation neither establishes independent catalog
provenance nor changes declared exposure. The source-side catalog must be
frozen and qualified separately before any claim of source-only inference.

## Report and selection behavior

The report schema is `legal-compact-catalog-token-selection/v1`, profile
`object-relational-compact-catalog-selection/v1`, and format
`one-step-allowed-logit-argmax/v1`.

Reports retain the entire offered score vector and its canonical SHA256,
offered/resulting prefixes, raw unconstrained argmax and score, constrained
selected ID and score, whether selection overrode the raw argmax, the exact
number of appended tokens, and the tie rule. `prefix_report` is the complete
unchanged public catalog-prefix report, with `prefix_report_sha256`. It retains
the full catalog, including unused declarations. Separate fields bind the
selection policy, codec, raw context bytes, canonical context, and inner catalog.

An empty prefix selects BOS if that is the only publicly admitted token. A
complete subset document can select EOS under the explicit optional-catalog
grammar. No offered ID is replaced or removed. A completed, rejected or
budget-exhausted prefix returns `status="no_selection"`, null selected ID/score,
zero appended tokens and an unchanged prefix. The original prefix status and
reason remain visible. Missing EOS or PAD is never repaired retrospectively.

Allowed IDs remain local grammar constraints. They do not prove that a complete
output fits the remaining budget. This prefix operation has no completed typed
prediction or `catalog_prediction_id`; downstream complete decoding must retain
the catalog owner's outer identity, because an effective AST can stay unchanged
when unused catalog declarations change.

`logits_origin_verified` and `head_compatibility_qualified` are false. Every
authority field is false; `training_mask` and `evaluation_gold_mask` are integer
zero. A high selected score, valid prefix or successful hash check establishes no
source meaning, role correctness, inference permission, learned accuracy,
statutory gold, graph admission or Lean proof authority.

## Reuse, custody and failures

The exact pinned old selector supplies only its bounded `_preflight`, `_copy`,
`_fingerprint`, `_argmax`, `_wire` and `_detach` primitives. Its public
`select_compact_content_token_v1` and grammar-bound `_prefix_report` are not
called. Grammar decisions come only from the new public
`compact_catalog_allowed_token_ids_v1`; its codec is also validated by the new
public codec hash function. No globals, module identities, old source files or
closure caches are replaced.

The selector validates the prefix receipt's closed schema, profile, policy,
raw/canonical context commitments, exact offered IDs, sorted unique plain-int
allowed IDs, status/reason/budget relationship, counts, false authorities and
complete seven-source producer population. The returned selection has nine
source records: this module, the old selector, catalog token owner, old token
owner, content owner, relational owner, AST, signatures and TDFOL core.

Fixed hashes, actual module paths/import anchors and bounded single-link source
snapshots are checked before imports and at closing. Physical device/inode,
mode, size, modification/change times and link counts are retained internally.
Original and captured inputs are checked again after the complete report has
been serialized. These are endpoint checks over a finite trusted source
generation, not a source lock, hostile-interpreter proof or operating-system
sandbox.

Bounds match the existing selector: 1 MiB combined captured inputs, 2 MiB full
report, 524,288 context bytes, 32,768 codec bytes, 32,768 score-vector bytes,
100,000 JSON items and depth 96. Whole-bound overflow raises without truncation.
Invalid independent hashes, foreign codec/context, malformed prefix receipts,
source drift and owner errors abort the operation rather than becoming model
rejection. Exceptions and interruptions propagate; if a closing fence also
fails, the original escaping exception remains primary and receives a note.

The old selector has no public replay-validator API, so this additive slice does
not invent one. A caller may retain the original inputs and independently pin
and recompute the full deterministic selection through the public function.

## Next integration boundary

Authored finite-score controls can qualify this selector without model work.
Actual numerical use requires an explicit compatible checkpoint/scorer and
generator successor, coordinated with the existing compact training owner.
Equal output width does not provide that compatibility. New batch intake needs
its own reviewed source closure and denominator-preserving versioned core;
adding functions to old pinned files would invalidate their retained consumers.
Source nominations, ordered roles, catalog exposure, unavailable inputs, raw
generated observations, and full catalog identities must survive those joins.
No new training, numerical migration, source permission or production default
is supplied by this module.
