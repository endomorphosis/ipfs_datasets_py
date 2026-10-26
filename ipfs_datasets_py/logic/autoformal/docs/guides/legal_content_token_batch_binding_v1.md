# Binding semantic token evidence to generated requests

This change hardens the existing
[`legal_relational_content_token_batch_evaluation_v1`](legal_relational_content_token_batch_evaluation_v1.md)
profile in `logic/autoformal/legal_relational_batch_evaluation_v1.py`. It adds
internal commitment checks around the existing public token/content owners.
The existing content-token APIs, schemas, per-observation context fields,
terminal taxonomy, complete raw decoder reports and shared selected-population
accounting loop remain the interface. No parallel semantic batch API, AST,
grammar, renderer, denominator or provenance owner is introduced.

This guide describes an authored candidate. Source inspection and authored
tests do not establish installation or a passing owned qualification. Execution
and closeout evidence must identify this exact source generation separately.

## Commitments checked together

Each generated observation retains its original IDs, their independent digest,
and a separately committed signature/ordered-role context. The source-context
hash in the selected population remains a different commitment from the
observation's `content_context_sha256`.

After the real public token decoder returns, the adapter requires:

- Returned IDs, codec identity and raw context hash equal the offered values.
- The returned canonical context hash equals canonical JSON computed from the
  exact offered context bytes after the public owner has validated those bytes.
- Recoverable generated content agrees with its UTF-8 text, hexadecimal bytes
  and SHA256. Unrecoverable content cannot claim fabricated byte commitments.
- A valid nested prediction retains generated identity and agrees with that
  content, canonical context, content/context hashes and constructor counts.

The adapter then invokes the existing public `decode_prediction_v1` with only
those committed content bytes and the original context's canonical bytes. It
requires the complete regenerated prediction to equal the retained nested
prediction, including its request, typed expression and all their commitments.
The request's independent canonical hash must also match its serialized bytes.
This target-free replay binds the content evidence to the request that reaches
the existing relational validator and comparator. It receives no reference,
archival identity sidecar, expected target tree or repair map.

A genuine rival request with its own correct SHA256 is insufficient to replace
only the request inside another prediction. A rival nested prediction likewise
cannot replace the prediction while retaining another content trace. Such
cross-owner disagreement is an operational refusal of the complete call. It
is never converted into a model rejection category, partial score or repaired
prediction. Arbitrary forged successful public owners are outside the trusted
owner contract; these checks do not establish general executed-bytecode
integrity or replace the token owner's grammar validation.

## Exact producer custody

Public `owner_pins` lists must contain the complete known producer population:
two descriptors for token prefix/candidate reports, and five for a generated
prediction. Every path must already belong to the fixed trusted closure; every
SHA256 and byte count must agree with its current source snapshot. A returned
descriptor can verify membership but cannot nominate an additional file read.
All returned authority values must be literal false, and training/evaluation
gold masks must be integer zero. Missing producers, false byte counts, promoted
masks and positive authority refuse the whole operation.

The two direct token/content source generations are snapshotted at their fixed
canonical paths before lazy imports, checked again after import and checked
through the existing content source fences. Their current import anchors and
fixed relational/AST/signature/TDFOL dependencies remain checked through the
existing `_content_sources` closure. The content cache stays separate from the
legacy and full-request compact caches. Detached original inputs and physical
source identities are checked before and after public calls and after complete
output serialization. A fresh checked-buffer owned qualification supplies
separate runtime compilation observations; source snapshots alone do not prove
arbitrary preloaded bytecode equivalence.

## Existing context and identity limits

The retained v1 interface supplies context on each generated observation. It
has no independent ordered context inventory for every selected occurrence and
no explicit available/unavailable decoding-context declaration. Missing and
unsupported occurrences remain in the complete selected denominator. A missing
or ill-typed generated-row context is still a malformed observation under that
existing contract. A malformed available context, wrong raw commitment, actual
owner/source failure, interruption or complete bound overflow still aborts the
operation. This patch does not manufacture a context for an unsupported row or
borrow one from a reference.

A full selected-population context-availability inventory remains a future
versioned intake decision. Context permission, source-only context production,
absence of answer leakage and support for broad signature catalogs remain
unverified. Every declared predicate must currently occur in a valid compact
tree. Context origin labels stay caller declarations; `decoder_declared` plus
`target_derived_label` receives no comparison credit. Relabelling context does
not establish independence or permission.

Generated identities and binder names remain generated. In the current genuine
authored roundtrip fixture, exact typed-expression equality and binder-sensitive
declared-structure equality are false while lexical-alpha structure equality is
true. Those are distinct existing comparator diagnostics. No archival IDs or
binder names are restored to improve a metric. The older, unlaunched alternative
76-case candidate is historical authored material and provides no execution
credit for this generation.

The legacy request-text and full-request byte interfaces retain their public
contracts and behavior. The shared batch owner's source hash necessarily changes;
reports from different source generations cannot be claimed byte-identical.
All bounds remain complete-operation limits, including 512 total content IDs
with BOS/EOS and the existing complete batch report cap. No evidence or selected
occurrence is dropped to fit them.

No learned output head, checkpoint migration, model inference, training,
statutory semantics, graph/Lean admission, provider-token savings or convergence
claim is established by this binding patch. All product authority remains false
and both eligibility masks remain zero.
