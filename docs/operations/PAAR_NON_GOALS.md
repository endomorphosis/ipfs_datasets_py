# Patent Automated Application Review (PAAR) — Non-Goals and Forbidden Automations

**Program:** `patent-automated-application-review-v1`  
**Task:** `PAAR-001` / `PAAR-140`  
**Goal:** `PAAR-G010` / `PAAR-G150`  
**Companion plan:** `docs/architecture/PATENT_AUTOMATED_APPLICATION_REVIEW_PLAN.md`  
**Report schemas:** `docs/architecture/paar_report_schemas.md`  
**Related portfolio policy:** `docs/operations/PATENT_LEGAL_PORTFOLIO_NON_GOALS.md`  
**Tests:** `tests/unit/processors/domains/uspto/test_paar_schema_docs_present.py`,  
`tests/security/test_paar_non_goals.py`

This document is the **authoritative permanent non-goals list** for the Patent
Automated Application Review (PAAR) program. Supervisors, agents, and operators
must **not** reopen forbidden workstreams as incomplete coverage.

PAAR screens portfolio and draft applications for **prior-art conflict risk**
and **MPEP / 37 C.F.R. package conformance**. It does **not** replace a natural
person for legal judgment, Patent Center final submission, payment, signature,
or IDS filing.

## Standing decision (fail-closed)

The following are **permanent non-goals**. Absence of these capabilities is
**intentional incompleteness**, not a true product gap to schedule as backlog.

| Forbidden automation | Status | Safe alternative |
| --- | --- | --- |
| **Patentability conclusions** (novelty, obviousness, allowability, validity, FTO) | **Forbidden** | Conflict risk tiers `unknown` / `low` / `medium` / `high` with evidence quotes; human counsel |
| **Auto Sign / Pay / Submit** | **Forbidden** | Human Patent Center handoff; filing-assist view-only with hard barriers |
| **Auto IDS file** | **Forbidden** | Human IDS review queue; natural person files IDS |
| **PPS automation** / **Google Patents scrape** | **Forbidden** | ODP automated US search; EPO OPS optional foreign; human PPS checklist |
| **Silent foreign / NPL coverage** | **Forbidden** | Named coverage gaps remain visible when unsearched |

### Locked policy statements

1. **Patentability conclusions are forbidden.** Conflict-risk reports, claim
   charts, conformance reports, and unified reviews never assert novelty,
   obviousness, allowability, patentability, invalidity, or freedom-to-operate.
   Allowed language: conflict risk tiers and package conformance statuses.
2. **Auto Sign / Pay / Submit is forbidden.** Hard-barrier controls (Sign,
   Certify / 11.18, Pay / Payment, Submit, checkout, charge, credit card, etc.)
   are never auto-clicked. Final submission is always a natural person.
3. **Auto IDS file is forbidden.** The system may build IDS **candidate queues**
   and bind human dispositions (`consider_ids`, etc.). It never files an IDS
   and never asserts 37 C.F.R. § 1.56 materiality automatically.
4. **PPS automation is forbidden.** Patent Public Search remains human-only.
5. **Google Patents scrape is forbidden.** Browser deep links for human review
   only; never scrape patents.google.com as a backend.
6. **Silent foreign / NPL coverage is forbidden.** Unsearched corpora force
   `unknown` or elevate aggregate risk / leave named gaps visible.

## Doctrine: conflict risk vs patentability

| Concept | In scope for PAAR? | Notes |
| --- | --- | --- |
| Conflict risk screening | Yes | Closed vocabulary: `unknown`, `low`, `medium`, `high` |
| Limitation overlap evidence | Yes | Quoted spans + method tags; not legal claim construction |
| Package conformance | Yes | `satisfied` / `unsatisfied` / `unknown` / `human_only` |
| Novelty / obviousness opinion | **No** | Permanent non-goal |
| “Safe to file without review” | **No** | Permanent non-goal |
| “No prior art exists” | **No** | Permanent non-goal |

## Fail-closed rules

* Missing authority corpus → `unknown` / `review_required`, never vacuous pass.
* Unsearched required corpus → cannot yield overall low-risk without named gap.
* Low claim OCR quality → automated conflict screening non-authoritative.
* Unknown obligation / unbound authority → `unknown` status.
* Private artifacts stay offline / tenant-isolated; no secret echo.

## Forbidden product language (examples)

Do **not** emit in automation outputs:

* “Claim is novel / obvious / patentable / unpatentable / allowable”
* “No prior art exists”
* “Safe to file without review”
* “Will be allowed / rejected” as a legal conclusion
* Auto Sign / Pay / Submit / file IDS pathways

## Allowed product language (examples)

* “Conflict risk: high / medium / low / unknown”
* “Limitation overlap evidence”
* “Package does not satisfy rule pack X (or unknown)”
* “Human review required before IDS / response”
* “auto_file_blocked=true”

## Safe alternatives

| Need | Use this | Do not use |
| --- | --- | --- |
| Automated public US prior-art search | **ODP** (`USPTO_ODP_API_KEY`) | Google Patents scrape; PPS scrape |
| Optional foreign metadata | **EPO OPS** | Scraping EPO/Google UIs |
| IDS preparation | Human IDS review queue | Auto-file IDS |
| Filing | Human Patent Center handoff | Auto Sign/Pay/Submit |
| Legal judgment | Licensed counsel | Automation “patentability” labels |

## Intentional incompleteness vs true gaps

**Intentional incompleteness** (do not reopen as backlog):

* Patentability conclusions
* Auto Sign / Pay / Submit / auto IDS file
* PPS / Google Patents scrape
* Silent foreign coverage claims

**True gaps** (may schedule work):

* Missing seed obligations for a supported scenario
* Bug in quality gate or fail-closed path
* Fixture / eval harness incompleteness
* Authority corpus binding when sources are available but not wired
* Exhaustive multi-corpus prior-art **diligence wiring** (US/ODP, foreign/EPO OPS,
  NPL must be searched or residual gaps named — never silent coverage)
* Portfolio live ops: EPO OPS foreign search, fuller PCT IFW packages, re-audit

### Exhaustive prior-art diligence (what it means)

**In scope:** require named corpora (`us_patents`, `foreign_patents`, `npl`) to be
searched via licensed APIs (ODP, EPO OPS) **or** leave explicit named residuals
that block vacuous “ready” dispositions.

**Forbidden:** claiming that all prior art worldwide was found or that no prior art exists.
**Forbidden:** any novelty, obviousness or patentability conclusion.
Exhaustive diligence is a **coverage process**, not a legal determination.

## Cross-references

* Plan: `docs/architecture/PATENT_AUTOMATED_APPLICATION_REVIEW_PLAN.md`
* Schemas: `docs/architecture/paar_report_schemas.md`
* Portfolio non-goals: `docs/operations/PATENT_LEGAL_PORTFOLIO_NON_GOALS.md`
* Handoff: `docs/operations/PATENT_CENTER_HUMAN_HANDOFF.md`

---

**Not legal advice.** Human remains responsible for counsel decisions and filing actions.
