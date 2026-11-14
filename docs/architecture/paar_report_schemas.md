# PAAR Report Schemas

**Program:** `patent-automated-application-review-v1`  
**Task:** `PAAR-001`  
**Goal:** `PAAR-G010`  
**Non-goals:** `docs/operations/PAAR_NON_GOALS.md`  
**Tests:** `tests/unit/processors/domains/uspto/test_paar_schema_docs_present.py`

This document defines the shared **machine-readable report vocabulary** for
Patent Automated Application Review. All lanes emit digests and statuses using
these schemas. Reports are **decision-support only** — not legal advice, not
patentability opinions, and not filing authority.

## Common invariants

* Schema pin + content digest on every report.
* Risk vocabulary closed set: `unknown` | `low` | `medium` | `high`.
* Conformance status closed set: `satisfied` | `unsatisfied` | `unknown` | `human_only`.
* Unified disposition closed set: `ready` | `review_required` | `not_ready`.
* `auto_file_blocked` always `true` on IDS-related surfaces.
* No patentability / novelty / obviousness conclusion fields.
* Fail closed: missing authority or corpus → `unknown` / `review_required`.
* Private claim bodies not written to ordinary logs.

---

## ConflictRiskReport@1

**Schema id:** `paar.ConflictRiskReport@1`  
**Interface:** `ConflictRiskReport@1`  
**Purpose:** Persist per-limitation × prior-art-hit conflict **risk** with
quoted evidence, method tags, coverage gaps, and optional human dispositions.

### Required top-level fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema` | string | `paar.ConflictRiskReport@1` |
| `report_id` | string | Stable id for this report instance |
| `application_number` | string | Normalized application number when known |
| `generated_at_utc` | string | ISO-8601 UTC |
| `content_digest` | string | sha256 hex of canonical payload (excl. wall-clock if needed) |
| `disclaimer` | string | Review-only; not patentability; not legal advice |
| `auto_file_blocked` | bool | Always `true` |
| `matter_risk` | string | Aggregate: `unknown` \| `low` \| `medium` \| `high` |
| `coverage_gaps` | array | Named unsearched corpora / adapters |
| `cells` | array | Limitation×hit risk cells |
| `dispositions` | array | Human disposition records (may be empty) |

### Cell object

| Field | Type | Notes |
| --- | --- | --- |
| `cell_id` | string | Unique cell id |
| `limitation_id` | string | From claim limitation model |
| `claim_number` | int | |
| `hit_id` | string | Prior-art hit identifier |
| `risk` | string | `unknown` \| `low` \| `medium` \| `high` |
| `method` | string | `lexical` \| `embedding` \| `structured` \| `unknown` |
| `confidence` | number | \[0, 1\] heuristic |
| `limitation_quote` | string | Bounded quote (or digest ref) |
| `hit_quote` | string | Bounded quote (or digest ref) |
| `source_links` | array | Optional SourceLink objects |

### Disposition object

| Field | Type | Notes |
| --- | --- | --- |
| `disposition_code` | string | `not_material` \| `consider_ids` \| `distinguish_in_remarks` \| `needs_counsel` \| `deferred` |
| `acknowledger_id` | string | Natural person id (required to bind) |
| `acknowledged_at_utc` | string | ISO-8601 |
| `cell_ids` | array | Cells covered |
| `notes` | string | Optional human notes |

### Forbidden fields / language

* `patentable`, `unpatentable`, `is_novel`, `is_obvious`, `novelty_conclusion`,
  `obviousness_conclusion`, `patentability_conclusion`, `will_be_allowed`
* Any path that files IDS or Sign/Pay/Submit

### Example (abbreviated)

```json
{
  "schema": "paar.ConflictRiskReport@1",
  "report_id": "crr:example:001",
  "application_number": "16000001",
  "generated_at_utc": "2026-08-06T00:00:00Z",
  "content_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "auto_file_blocked": true,
  "matter_risk": "medium",
  "coverage_gaps": [
    {"kind": "foreign_patent", "status": "unsearched"}
  ],
  "cells": [
    {
      "cell_id": "cell:lim:c1-1:hit-1",
      "limitation_id": "lim:c1-1",
      "claim_number": 1,
      "hit_id": "hit-1",
      "risk": "medium",
      "method": "lexical",
      "confidence": 0.62,
      "limitation_quote": "…",
      "hit_quote": "…"
    }
  ],
  "dispositions": [],
  "disclaimer": "Review-only conflict risk screening. Not a novelty, obviousness, or patentability determination. Not legal advice. auto_file_blocked=true."
}
```

---

## ConformanceReport@1

**Schema id:** `paar.ConformanceReport@1`  
**Interface:** `ConformanceReport@1`  
**Purpose:** Evaluate application package inventory / extracts against the
obligation catalog (MPEP guidance + 37 C.F.R. / Title 35 controlling cites).

### Required top-level fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema` | string | `paar.ConformanceReport@1` |
| `report_id` | string | |
| `application_number` | string | When known |
| `generated_at_utc` | string | ISO-8601 UTC |
| `content_digest` | string | sha256 hex |
| `catalog_id` | string | Obligation catalog id |
| `catalog_version` | string | |
| `catalog_digest` | string | Content digest of catalog used |
| `application_type` | string | e.g. `utility` |
| `scenario` | string | e.g. `new_application` |
| `overall_status` | string | `satisfied` \| `unsatisfied` \| `unknown` \| `human_only` |
| `results` | array | Per-obligation evaluation rows |
| `disclaimer` | string | Review-only; form instructions not controlling law |

### Result row

| Field | Type | Notes |
| --- | --- | --- |
| `obligation_id` | string | |
| `status` | string | `satisfied` \| `unsatisfied` \| `unknown` \| `human_only` |
| `severity` | string | From catalog |
| `authority_cites` | array | Echo of cites with tiers |
| `evidence` | array | Predicate outcomes |
| `fail_closed` | string | Catalog fail-closed behavior applied |
| `notes` | string | |

### Authority tier rules

* `statute` and `regulation` may be `is_controlling: true`.
* `guidance` (MPEP) is **never** silently elevated above CFR/statute.
* Missing authority corpus → overall and affected rows stay `unknown`.

### Forbidden

* Treating MPEP as controlling over 37 C.F.R.
* `patentability` conclusion fields
* Auto Sign/Pay/Submit side effects

---

## UnifiedApplicationReview@1

**Schema id:** `paar.UnifiedApplicationReview@1`  
**Interface:** `UnifiedApplicationReview@1`  
**Purpose:** Single operator entrypoint report composing conflict risk,
conformance, diligence residuals, and exit disposition for continuous review.

### Required top-level fields

| Field | Type | Notes |
| --- | --- | --- |
| `schema` | string | `paar.UnifiedApplicationReview@1` |
| `review_id` | string | |
| `application_number` | string | |
| `generated_at_utc` | string | |
| `content_digest` | string | |
| `disposition` | string | `ready` \| `review_required` \| `not_ready` |
| `exit_code_hint` | int | 0 ready, 1 review_required, 2 not_ready/error |
| `conflict_risk_ref` | object | `{report_id, path?, content_digest, matter_risk}` |
| `conformance_ref` | object | `{report_id, path?, content_digest, overall_status}` |
| `claim_model_ref` | object | `{content_digest, authority_mode, quality_score}` |
| `coverage_gaps` | array | Union of named gaps |
| `diligence_residuals` | array | Optional gap-closure pack pointers |
| `auto_file_blocked` | bool | Always `true` |
| `disclaimer` | string | Not patentability; human filing barrier absolute |

### Disposition rules (normative)

| Condition | disposition |
| --- | --- |
| Missing authority or structural failure | `not_ready` or `review_required` (never `ready`) |
| Low OCR quality on claims | `review_required` |
| Matter risk high / medium without human disposition | `review_required` |
| Conformance `unsatisfied` on blocking obligations | `not_ready` or `review_required` |
| Conformance `unknown` | cannot be `ready` without human acceptance of named gaps |
| All gates pass with named residual gaps accepted | `ready` (still not a legal “file” authorization) |

### Exit codes (operator CLI)

| Code | Meaning |
| --- | --- |
| 0 | `ready` (review support complete; human still owns filing) |
| 1 | `review_required` |
| 2 | `not_ready` / error |

Never exit 0 with a patentability implication.

---

## Claim limitation model (input schema pin)

**Schema id:** `paar.claim-limitation-model.v1`  
**Module:** `ipfs_datasets_py/processors/domains/uspto/claim_limitation_model.py`

| Field | Notes |
| --- | --- |
| `quality.authority_mode` | `authoritative` \| `review_required` \| `non_authoritative` |
| `quality.quality_score` | \[0, 1\] |
| `quality.low_ocr_quality` | bool |
| `claims[]` / `limitations[]` | Independent/dependent structure + spans |

---

## Obligation catalog (input schema pin)

**Schema id:** `paar.obligation-catalog.v1`  
**Module:** `ipfs_datasets_py/processors/domains/uspto/analysis/obligation_catalog.py`  
**Seed:** `obligation_catalog_seed.json`

Each obligation: `id`, authority cite (+ tier), applicability, evidence
predicates, severity, fail-closed behavior. MPEP = guidance tier.

---

## Document control

| Field | Value |
| --- | --- |
| Schema | `paar.report-schemas.doc@1` |
| Status | active |
| Not legal advice | true |
| Human filing barrier | absolute |
