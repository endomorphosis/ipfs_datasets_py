# Record compositional source reviews

The source-only review adapter records declarations for the prepared 64-item compositional packet, including incomplete fields, exact agreement and disagreements. It preserves the original source and context envelopes. Every training and evaluation mask remains zero, including when complete declarations agree. Authentication of reviewer identity and independence, followed by semantic adjudication, requires a separate evidence process.

The [dictionary adapter](../../ipfs_datasets_py/logic/legal_ir/canonical_binding_review.py), [file workflow](../../ipfs_datasets_py/logic/legal_ir/canonical_binding_review_workflow.py) and [command line](../../scripts/ops/legal_ir/record_binding_reviews.py) extend the existing review infrastructure through a new source-only schema. They reuse the unchanged annotation and meaning-signature helpers in the richer-review admission owner. They do not reinterpret the older 34-item packet, load its authored references or change its recorded results.

## Give reviewers the source packet

Distribute only the original `binding-review-packet-01/reviewer_items.json`, its reviewer manifest and the new `submission_guide.json`. The packet contains source text, an exact empty `none_required` context, input identities and eight blank annotation slots. Grouping, proposed splits and organizer surfaces are private; candidate predictions and expected answers are excluded. Do not give reviewers the organizer manifest or private recording receipts.

An actual reviewer fills a copy of the public packet. Preserve its schema, instructions, source, context, hashes and item IDs. A nonempty subset of items or a different item order is allowed. Null values remain unanswered. Filling a syntactically complete declaration does not establish that its meaning is faithful or that its author is independent.

## Fill the annotation slots

| Field | Declaration |
| --- | --- |
| `interpretation_status` | `normative`, `no_normative_rule`, `ambiguous`, `unsupported`, or null while unanswered. |
| `ambiguity`, `unsupported_meaning` | Explicit Boolean values when reviewed; null remains unanswered. |
| `normative_rules` | An ordered list of seven-facet rules, an explicit reviewed empty list where applicable, or null while unanswered. |
| `freeform_qualifier_scope` | Describe connectives, attachment, timing and any meaning beyond flat facets. Normative rules with qualifiers require a nonempty description. |
| `notes` | Rationale for absence of a normative rule, ambiguity or unsupported meaning; optional for ordinary normative declarations. |
| `reviewer_id`, `reviewed_at_utc` | Declare identity and a calendar-valid UTC time only after an actual review. These declarations do not authenticate a person. |

Every rule has exactly `modality`, `actor`, `action`, `object`, `conditions`, `exceptions` and `temporal`. Modality uses `O`, `P` or `F`; actor and action are nonempty strings; an empty object string explicitly records no object. Qualifier facets are lists of nonempty strings. Order and repeated qualifiers are retained. Null whole facets remain unanswered; null members inside a qualifier list are invalid.

For `normative`, propose at least one rule and set both flags false. For `no_normative_rule`, supply an explicit empty rule list, false flags and a rationale. For `ambiguous`, set ambiguity true and explain competing interpretations or missing information. For `unsupported`, set unsupported meaning true and explain the representation gap. Tentative rules can remain in ambiguous or unsupported declarations. An explicit empty scope string records no additional scope description where permitted; it is distinct from null.

## Run the recorder

From the datasets repository root, a readiness check uses the frozen public packet and its exact file-byte SHA256, without any submission arguments:

```bash
python scripts/ops/legal_ir/record_binding_reviews.py \
  --reviewer-packet /home/barberb/lift_coding/artifacts/autoformalization-alignment-20261003/binding-review-packet-01/reviewer_items.json \
  --expected-packet-file-sha256 8a8303ea83fe22899f798703e7931b1f48a8aa0afb01c7d6980a7d3e9301701e \
  --output-directory /tmp/binding-review-recording-01
```

Use a fresh destination for each run. To record actual submitted copies, add one repeated path/digest pair for each file:

```bash
  --submission /path/to/reviewer_a.json <exact-submission-file-sha256> \
  --submission /path/to/reviewer_b.json <exact-submission-file-sha256>
```

The workflow separately computes the blank packet's canonical content SHA256: `a8f465c7950e34ce11f69a5a900d79895f5e19545a2082da75eb9ddf59815655`. The dictionary API requires this content pin, using sorted compact UTF8 JSON with no NaN or trailing newline. The command-line file pins hash the original bytes, including formatting. Neither digest authenticates the reviewer or the interpretation.

Inputs must be ordinary finite UTF8 JSON within the 16 MiB file bound. Duplicate keys, UTF16/32, BOM-prefixed JSON, altered envelopes, stale digests, duplicate submissions and repeated declared reviewer IDs for the same input are rejected. Existing filesystem helpers reject symlink components and nonregular files, and recheck bound input and implementation bytes before publication. Their exposed-input path heuristic excludes components marked sealed, holdout, final or test; it is a scope heuristic rather than a semantic check. The API allows at most 64 items per packet and 20 submissions; rule, qualifier, text, depth and aggregate-byte limits are specified in the submission guide.

## Interpret the private receipt

The workflow writes `receipt_private.json`, `report_private.json` and `submission_guide.json` into a new directory with mode `0700`; files use mode `0600`. The report binds five explicit executing owners, inputs and outputs. It leaves full dependency attestation unavailable. Permissions and audience labels do not establish identity or reviewer independence.

The receipt distinguishes `pending`, `single_review`, `agreed_multiple_reviews`, `disputed`, `ambiguous` and `unsupported`. The review names describe recorded declarations. Mechanical agreement compares exact interpretation status, flags, ordered full rules and scope wording, excluding notes, identity and timestamp. Different order or wording can therefore remain disputed even if a later reviewer finds semantic equivalence. Incomplete declarations remain recorded without contributing a complete signature. No authored reference or model answer selects a declaration or resolves a dispute.

Every item retains external adjudication pending and all five masks zero. Authenticated review counts, semantic gold, training/evaluation admission, independent fidelity, proof authority and qualification remain absent. The recorder provides no path to enable masks. Actual independent review, authenticated provenance and adjudication must precede a separately versioned label-admission contract. The authored templates also remain distinct from a disjoint natural-source confirmation corpus.

Focused tests use synthetic fixtures only; campaign readiness uses an empty submission list and creates no human answers, identities, attestations or adjudications.
