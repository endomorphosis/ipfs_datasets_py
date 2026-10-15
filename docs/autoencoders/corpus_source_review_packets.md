# Complete source-first review packets

`logic/autoformal/corpus_source_review_packets.py` prepares the original pending
source/context requests for inspection. It regenerates the complete original
source preparation through `corpus_source_review`, preserves every occurrence and
competitor, materializes full source views, and creates blank response guides.
It creates no reviewer, signed claim, completed response or applied decision.

## Inputs and fixed replay

Call `prepare_source_review_packets` with the same five source-input arguments
as `prepare_source_review_requests`, plus independently selected
`expected_preparation_manifest_sha256`. That SHA256 is the FULL canonical hash
of the existing complete source-preparation manifest, including its record CID.
It is distinct from its payload CID and any pretty JSON transport hash.

The five arguments are `alignment_corpus_bytes`,
`expected_alignment_corpus_pins`, `alignment_replay_inputs`,
`source_report_bytes`, and `expected_source_report_pins`. They retain complete
immutable transports, raw/FULL report hashes, original Parquet replay and every
supplied official acquisition. Optional `source_review_limits` lowers the
inherited source profile; its changed preparation manifest must be independently
pinned. Optional `limits` lowers the packet profile. Neither accepts callbacks
or raised/unknown limits. There is no loader, signer, registry or clock default.

The existing owner repeats full source/alignment/context/handoff regeneration
once per packet preparation. Every byte namespace and bounded nested source
input is checked before operation-owner imports. The public packet import itself
performs no source decoding, crypto verification, model, network or clock work.
Producer file pins are checked before preparation and after final comparison.

## Complete evidence and request identities

The output has exactly eleven components: `manifest`, `pages`, `source_views`,
`official_documents`, `document_parts`, `parent_packets`, `unit_packets`, `response_guides`,
`question_catalog`, `selector_projections`, and `comparison_evidence`.
Everything except the manifest is an ordered list of sealed records.

Source views retain complete exact decoded parent, official normalized and
rendered fields. Each binds the unchanged source-version record, literal text,
raw UTF8 text hash/CID, character/byte lengths and every original field pointer
and observation membership. Repeated acquisitions can share a version/view;
their acquisition records and memberships remain distinct. Normalized/rendered
profiles are distinct, and no extracted offset is relabelled as raw HTML.

Official document records retain every original acquisition, both full-view
references and original alignment-report pointer/hash. `view_report_transport`
and `rendered_field_transport` preserve each complete original structure as a
head and ordered `document_parts`. The head retains every scalar, dictionary and
empty array; each nonempty array is restored at its original JSON pointer from
parts with original item indices, exact values, whole-array hashes and CID/FULL
hash references. Array indices address JSON entries, not extracted text or HTML.
Each transport also binds the whole reconstructed value and original report
field. Reconstruction must equal the original before preparation succeeds.
The head is a transport wrapper, not an original extraction-report schema.
Unavailable rendered views remain explicit nulls. Shared comparison records retain every original parent/document cell,
including zero-match, unavailable and off-URL cells, its unchanged corpus record,
and full original alignment and context comparison bodies with both report pins.

The shared projection catalog preserves every original projection index/value,
whole-value hash and context-report pointer. Each projection resolves to its
whole source view and verifies literal text, Unicode and UTF8 half-open geometry.
Original compact references inside context units are retained verbatim; inspect
them through this catalog. Neighboring block references resolve through complete
official document structures. The manifest binds the original context authority.

A unit packet embeds the unchanged source request, original handoff unit and
original context unit when present. It references the original subject CID/FULL
hash and dependency-manifest hash, preserves all comparison identities, and
quotes the original physical occurrence with its required-unavailable core
context. Rendering surrounding evidence does not make that context qualified.
The full source preparation remains an explicitly referenced external dependency
for signing subjects and dependency manifests; these presentation packets are
not a replacement for the existing authentication inputs.

Parent packets group units without deduplicating physical occurrences or sorting
by text. Original queue ordinals remain global identities. Ordered pages bind
all unit and guide CIDs/FULL hashes; counts and group memberships are complete.
No candidate model/compiler interpretation outputs are included in this source
presentation. That does not establish candidate blindness for a human: actual
prior/organizer exposure remains a declared question.

## Blank response guides and limits of authentication

Each guide has nine active source/context evidence answer rows with null
`disposition`, `finding` and `rationale`, and empty `evidence_refs`. Seven semantic
or proof questions retain null answers and deferred status. Reviewer identity,
role, time and exposure declarations are null. `blank_not_a_review` is literal:
a guide is not a submission, authenticated review or reviewer assignment.

The existing source claim schema/action/audience appear only as instructions.
Signatures remain owned by `corpus_source_review.assess_source_review_groups`.
This packet module accepts no completed responses and performs no signing,
verification, disagreement adjudication or decision application. Its validator
rejects modifications to blank guides; a completed response needs a separate
versioned response record bound to the exact request/subject/slot/evidence IDs.

Unknown or unavailable evidence must remain unresolved. A later typed response
recorder must check answer contents and disagreements, including contradictions
between unknown/open answers and signed `declared_complete` or
`resolved_by_evidence` declarations. The existing signature verifier checks
selected-key byte claims and evidence hashes; it does not interpret typed answer
contents or establish human identity, competence, independence or legal truth.
All source decisions, semantic graph/training/Lean admission flags remain false.

## Bounded validation and delivery

Every record, page and manifest retains the common 1 MiB envelope. The separate
complete packet collection cap is 64 MiB; limits also bound six parents,
32 source views, 8,192 units, 4,096 selector projections and 256 pages with at most
64 entries each. Document structures have at most 1,024 parts with at most 128
complete original array entries per part; byte caps can split them earlier.
Lower item caps repartition completely, while lower total-part caps can refuse.
An inline complete view, comparison, structure head or single array item above
1 MiB is refused;
no text or population is cropped. Larger transports require another qualified
profile. Underlying original-file verification remains with the inherited owner;
these are bounded supplied transports/records, not an absolute process-memory
or installed-distribution custody guarantee.

`validate_source_review_packets(bundle, **original_inputs)` bounds/detaches the
entire offered output before source replay, regenerates the full packet once,
and compares every component and producer pin. Repaired outer seals, omitted
memberships, altered source geometry or completed-looking answers cannot replace
that replay. Lower page caps repartition completely or refuse.

A delivery may include derived Markdown for inspection. Complete field text is
shown literally and occurrence quotes as JSON strings, preserving whitespace and
escapes; Markdown is a display aid rather than an authentication gate. Reviewers
should use sealed records and independently pinned exact evidence bodies for
responses. Candidate evidence can remain available while actual trust, reviews,
semantic interpretation and scoped graph/Lean qualification are still pending.
