# Record richer source/context reviews

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | formalization / autoencoder development |
| Source of truth | `alignment_richer_review.py`, `alignment_richer_review_admission.py`, `alignment_richer_review_workflow.py`, and `admit_alignment_richer_reviews.py` |
| Last verified | 2026-10-03 |
| Audience | developer, review organizer |

The richer review packet contains 34 exposed, authored source/context items.
This workflow records submitted annotations, incomplete fields and mechanical
agreement without creating independent adjudication or source-fidelity
authority. A run with no submissions checks the prepared packet and produces
a pending receipt. It does not supply answers or create reviews.

This packet is separate from the original 40-item empty-qualifier review queue.
Its input identities include separately declared context, and its annotations
can describe multiple rules and qualifier scope. The earlier admission schema
cannot review these richer items.

## Prepare the reviewer-facing material

Use the existing richer [blank preparation](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review.py).
Give a reviewer only the original `reviewer_payload`, its `reviewer_manifest`,
and the new `submission_guide.json`. The full bundle, organizer payload,
authored reference key, compiler output, retrieval results and private admission
receipts are organizer material. Their filenames identify the intended audience;
the names alone do not enforce access control.

The packet includes the exact source text and separately declared context text
and bindings. Two items have the same source text but different assumptions.
Their input hashes and pseudonyms are distinct; preserve both rather than
deduplicating them by source hash. Reviewers should interpret only the input
shown to them. Unsupported scope, variable binding, modality or time semantics
should be described explicitly rather than forced into seven flat facets.

An actual reviewer completes a copy of the reviewer payload. Preserve its
schema, instructions, source/context envelopes and item identities. A submission
may contain a nonempty subset of items and reorder them. Enter a declared reviewer ID and
UTC review timestamp only for an actual review. The workflow does not contact
reviewers, generate annotations or authenticate identities.

## Run a preparation audit or record submissions

From the datasets repository root, run the
[CLI](../../scripts/ops/legal_ir/admit_alignment_richer_reviews.py) with the SHA-256
of the existing full private bundle's file bytes and a fresh output directory:

~~~bash
python scripts/ops/legal_ir/admit_alignment_richer_reviews.py \
  --review-bundle /path/to/review_bundle_private.json \
  --expected-bundle-sha256 <bundle-file-sha256> \
  --output-directory /tmp/richer-review-admission-01
~~~

Omitting `--submission` is intentional for a readiness audit. All 34 items
remain pending and no completed review is invented. To record an actual
submission, add a repeated path/digest pair for each submitted file:

~~~bash
python scripts/ops/legal_ir/admit_alignment_richer_reviews.py \
  --review-bundle /path/to/review_bundle_private.json \
  --expected-bundle-sha256 <bundle-file-sha256> \
  --submission /path/to/reviewer_a.json <submission-file-sha256> \
  --submission /path/to/reviewer_b.json <submission-file-sha256> \
  --output-directory /tmp/richer-review-admission-02
~~~

Digests bind exact file bytes. They do not authenticate the person who supplied
the file. Use a new destination for every admission generation and retain the
original packet and submissions. The workflow rejects duplicate JSON keys,
nonfinite values, oversized or nonregular inputs, symlink inputs, stale digests
and altered source/context envelopes. It excludes input paths explicitly named
as sealed, holdout, final or test material before opening them; that path check
is a conservative scope heuristic, not evidence of semantic correctness.

## Fill annotations without inventing an interpretation

The eight annotation fields are `interpretation_status`, `ambiguity`,
`unsupported_meaning`, `normative_rules`, `freeform_qualifier_scope`, `notes`,
`reviewer_id` and `reviewed_at_utc`.

| Interpretation status | Reviewed content |
| --- | --- |
| `null` | Unanswered; null fields remain pending. |
| `normative` | At least one proposed rule; ambiguity and unsupported flags are explicitly false. |
| `no_normative_rule` | An explicit empty rule list, false ambiguity/unsupported flags, and a reason in notes. |
| `ambiguous` | An explicit ambiguity flag and notes explaining alternatives or required clarification; tentative rules may be retained. |
| `unsupported` | An explicit unsupported flag and notes describing meaning beyond the representation; tentative rules may be retained. |

Each proposed normative rule has modality, actor, action, object, conditions,
exceptions and temporal facets. Record qualifier scope and relationships in
`freeform_qualifier_scope`; a nonempty explanation is required for normative
rules with qualifiers. An empty string explicitly records no additional scope
description. An empty qualifier list is a reviewed absence for that facet;
`normative_rules=null` is not interchangeable with `normative_rules=[]`.

Syntactically complete annotations require the interpretation, flags, rule list,
every facet of each proposed rule, scope field, declared reviewer ID and valid
UTC timestamp. An empty object string explicitly records no object; a null
object facet remains unanswered. Notes are optional
for ordinary normative interpretations and required where a rationale is
needed. A correctly typed incomplete annotation stays pending. Neither this
completion check nor the chosen status establishes that the interpretation is
faithful to the source.

Agreement compares interpretation status, ambiguity and unsupported flags,
ordered full rules and the exact free-form scope description. Notes, identities
and timestamps do not determine the semantic signature. Different wording or
ordering can therefore remain mechanically disputed even when a human might
later reconcile it. Preserve the original submissions; do not resolve a dispute
by selecting the authored reference or the model's answer. The admission helper
performs no authored-reference scoring.

The receipt's operational item statuses are `pending`, `single_review`,
`agreed_multiple_reviews`, `disputed`, `ambiguous` and `unsupported`.
`no_normative_rule` is an interpretation status, so an undisputed complete
absence declaration is still a single or agreed-multiple review. Unanimous
ambiguity and unsupported declarations retain their respective item statuses.
Distinct declared reviewer IDs count declarations rather than authenticated
people, and no status automatically resolves the item.

## Interpret the outputs and the remaining review requirement

The [workflow](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_workflow.py)
writes `report_private.json`, `receipt_private.json` and `submission_guide.json`.
The report binds the packet, submissions, listed implementation files and
output artifacts. The private receipt records annotation completeness,
mechanical agreement and disputes. The guide explains how to submit a copy of
the original source/context packet; it supplies no proposed interpretation.
The new output directory uses mode `0700` and its files use mode `0600`.

All qualification, production admission, source-semantics and proof-authority
flags remain false, including when multiple declared reviewer IDs agree.
Reviewer identity and independence from the source author remain
unauthenticated. Primary independently adjudicated fidelity stays unavailable
with a null value, and useful native proof coverage stays unrun. No model,
encoder, prover, training or sealed evaluation runs in this workflow.

The next evidence requirement is actual candidate-blind review by independent
people, followed by separately authenticated identity/independence evidence and
explicit resolution of disagreement and unexpressed scope. Their annotations
must remain distinct from the authored labels until that adjudication occurs.
A recorded submission or exact agreement alone does not qualify the parser,
the autoencoders, the source embeddings or the numerical retrieval pilot.

Focused validation from the datasets root:

~~~bash
python -m pytest -q tests/unit/logic/formalization/autoencoder/test_admit_alignment_richer_reviews.py
~~~
