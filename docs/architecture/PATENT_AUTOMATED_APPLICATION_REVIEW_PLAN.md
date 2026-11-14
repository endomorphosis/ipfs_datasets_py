# Patent Automated Application Review (PAAR) Plan

**Program id:** `patent-automated-application-review-v1`  
**Task prefix:** `## PAAR-`  
**Goal prefix:** `PAAR-G`  
**Merge target:** `feature/patent-automated-application-review`  
**Depends on:** completed `patent-legal-intelligence-v1` (PATLAW) foundation  
**Companion artifacts:**

| Artifact | Path |
| --- | --- |
| Objective heap | `docs/architecture/patent_automated_application_review.objectives.md` |
| Taskboard | `docs/architecture/patent_automated_application_review.todo.md` |
| Scheduler config | `config/agent_supervisor_patent_automated_application_review.json` |

This plan is machine-ingestible by `ipfs_accelerate_py.agent_supervisor`
(objective daemon / bundle supervisor / multi-lane implementation).

---

## 1. North star

Build an **automated application review control plane** that, for every portfolio
matter (and for draft packages before filing):

1. **Prior-art conflict screening** — searches public US (+ optional foreign /
   NPL) corpora against claim limitations, ranks **conflict risk** with
   evidence quotes, and queues human IDS / remarks review.
2. **MPEP / 37 C.F.R. conformance** — checks the application package against
   time-versioned rule packs and authority excerpts, failing closed to
   `unknown` / `review_required` when authority or evidence is missing.
3. **Continuous portfolio loop** — re-runs when claims, IFW, priority dates, or
   corpus snapshots change; never Sign / Pay / Submit / auto-file IDS.

### Product outcome (operator view)

```text
portfolio matter / draft package
        │
        ▼
┌───────────────────┐   ┌────────────────────────┐
│ Claim model       │   │ Authority rule catalog │
│ (limitations,     │   │ (MPEP + 37 CFR packs)  │
│  dependencies)    │   └───────────┬────────────┘
└─────────┬─────────┘               │
          │                         │
          ▼                         ▼
┌───────────────────┐   ┌────────────────────────┐
│ Multi-corpus      │   │ Package conformance    │
│ prior-art search  │   │ (format + formalities) │
│ + date cutoffs    │   └───────────┬────────────┘
└─────────┬─────────┘               │
          ▼                         │
┌───────────────────┐               │
│ Conflict risk     │               │
│ matrix + report   │               │
└─────────┬─────────┘               │
          └───────────┬─────────────┘
                      ▼
           Unified Application Review Report
           (pass / review_required / not_ready)
                      │
                      ▼
        Human IDS / remarks / counsel gates
        (never automated filing)
```

---

## 2. Why a new program (PAAR vs PATLAW)

PATLAW delivered the **foundation**: processors, privacy, authority acquisition,
ODP/EPO/NPL adapters, claim charts, filing-obligation packs, portfolio export
loop, gap packages, and submission audits. The board is largely **complete**.

PAAR is the **productization layer** the operator still needs:

| Need | PATLAW today | PAAR target |
| --- | --- | --- |
| Prior-art “conflict” | Search + lexical distinguishability matrix; operator-driven | **Automated risk tiers** per claim limitation vs hits, with refresh triggers |
| “Would this block us?” language | Explicitly forbidden patentability conclusions | **Conflict risk screening** language (overlap evidence), still **not** novelty/obviousness legal opinions |
| MPEP/CFR conformance | Filing packs + rules/format audit + local excerpts | **Full obligation catalog** mapped to package facts, continuous re-check |
| Continuous review | Manual CLI steps | **Scheduler + change detection + portfolio fan-out** |
| Parallel agent work | PATLAW board drained | **New goal/task board** with disjoint parallel lanes |

---

## 3. Non-goals and hard barriers (normative)

**Never automate**

- Patent Center login / MFA / Sign / Pay / Submit
- Auto-file IDS or assert 37 C.F.R. § 1.56 materiality
- Google Patents or Patent Public Search scraping / UI automation
- Patentability, validity, infringement, or FTO legal opinions

**Always**

- Fail closed: missing authority or corpus → `unknown` / `review_required`, never vacuous pass
- Named coverage gaps (foreign, NPL, PPS human) remain visible
- Private artifacts stay offline / tenant-isolated; no secret echo
- Every finding binds evidence (document id, span or IFW code, authority cite)
- Human remains responsible for counsel decisions and filing actions

**Allowed product language**

- “Conflict risk: high / medium / low / unknown”
- “Limitation overlap evidence”
- “Package does not satisfy rule pack X (or unknown)”
- “Human review required before IDS / response”

**Forbidden product language**

- “Patentable / unpatentable / invalid / will be allowed”
- “No prior art exists”
- “Safe to file without review”

---

## 4. Reuse map (do not fork)

| Capability | Existing module(s) | PAAR extends |
| --- | --- | --- |
| ODP prior-art search | `prior_art_search_client`, `prior_art_runtime` | Date-correct queries, golden eval, conflict scoring |
| Foreign / NPL gaps | `prior_art_operator_extensions`, EPO/NPL clients | Continuous gap refresh; never silent close |
| Claim charts | `claim_chart_v2`, distinguishability matrix | Risk tiers + conflict report schema |
| Filing rules | `analysis/filing_rule_packs`, `filing_obligation_processor` | Obligation catalog + conformance engine |
| Format audit | `application_rules_audit` | Continuous gate + claim OCR quality SLOs |
| Authority corpus | MPEP/CFR materializers, `public_legal_index_client` | Rule→authority binding digests |
| Gap closure | `application_gap_closure` | Inputs to continuous review |
| Portfolio loop | `portfolio_automation`, `portfolio_cli` | Review orchestrator + scheduler |
| GraphRAG exports | `portfolio_graphrag` | Evidence retrieval for conflict quotes |
| Privacy | `privacy`, `privacy_sinks` | Content-free review emits |

---

## 5. Goal tree (summary)

```text
PAAR-G000  Automated application review control plane
├── PAAR-G010  Doctrine, schemas, non-goals seal
├── PAAR-G020  Claim limitation model fidelity
├── PAAR-G030  Prior-art conflict risk engine
├── PAAR-G040  Multi-corpus search orchestration
├── PAAR-G050  Conflict report + human disposition
├── PAAR-G060  MPEP/CFR obligation catalog
├── PAAR-G070  Package conformance engine
├── PAAR-G080  Continuity / priority / new-matter diligence
├── PAAR-G090  Continuous portfolio review scheduler
├── PAAR-G100  Unified review orchestrator (single entrypoint)
├── PAAR-G110  GraphRAG + authority-linked findings
├── PAAR-G120  Evaluation harness + golden fixtures
├── PAAR-G130  Operator dashboard, alerts, handoff
├── PAAR-G140  Agent-supervisor lane integration
└── PAAR-G150  Safety / privacy / non-goal enforcement tests
```

### Parallelism waves

| Wave | Goals (max parallel) | Unblocks |
| --- | --- | --- |
| 0 Seal | G010 | All lanes |
| 1 Foundations | G020, G060, G150 (partial), G120 (scaffold) | Engines |
| 2 Engines | G030, G040, G070, G080 | Reports |
| 3 Integration | G050, G100, G110 | Product loop |
| 4 Ops | G090, G130 | Continuous ops |
| 5 Supervisor | G140 | Multi-agent execution |
| 6 Hardening | G120 complete, G150 complete | Release gate |

---

## 6. Parallel lanes (agent supervisor)

| Lane id | Owns | Conflict domain |
| --- | --- | --- |
| `paar-docs` | Plan, objectives, todo, scheduler, non-goals | `docs/architecture/PATENT_AUTOMATED_*`, config |
| `paar-claims` | Claim parse, limitation graph, OCR quality | `prior_art_search_client` claim loaders, OCR bridges |
| `paar-conflict` | Conflict risk model, matrix, report schema | new `conflict_*` modules under patent/uspto |
| `paar-search` | Multi-corpus orchestration, date cutoffs, journals | adapters + runtime search plans |
| `paar-rules` | MPEP/CFR obligation catalog | rule packs + authority binding |
| `paar-conform` | Package conformance engine | `application_rules_audit`, filing packs |
| `paar-diligence` | Priority/new-matter/family diligence | `application_gap_closure` extensions |
| `paar-orchestrator` | Unified review pipeline CLI/API | thin composition only |
| `paar-schedule` | Continuous review triggers | portfolio scheduler |
| `paar-ux` | Dashboard, alerts, handoff packages | portfolio emit surfaces |
| `paar-eval` | Golden fixtures, metrics | tests/fixtures only |
| `paar-safety` | Privacy, non-goal, fail-closed tests | tests/security + doctrine tests |
| `paar-supervisor` | Lane matrix, launch recipe, validator | agent_supervisor data for PAAR |

**Conflict policy default:** a task owns only its listed `Outputs` / `Predicted files`
while concurrent. Shared `__init__` / CLI registries belong to orchestration
tasks after leaf modules land.

---

## 7. Workstream detail

### 7.1 Prior-art conflict screening (G020–G050)

**Claim model**

- Deterministic claim tree: independent/dependent, limitation spans, reference
  numerals, antecedent flags (heuristic, human-reviewable).
- OCR quality score gates whether automated conflict screening is authoritative
  or must fall back to human claim PDF review.

**Search orchestration**

- Per-limitation query plans (CPC/IPC, free-text, boolean) with **priority /
  effective filing date cutoffs** (already started in ODP body builder).
- Corpora: US public (ODP), foreign (EPO OPS optional), NPL (metadata + rights),
  family/citation expansion, applicant/examiner IDS sets as seeds.
- Journal every query; named gaps when corpus unsearched.

**Conflict risk engine**

- Inputs: claim limitations × prior-art hit text/spans.
- Outputs: per-cell risk `unknown | low | medium | high` with evidence quotes,
  method (`lexical | embedding | structured`), confidence, and **no legal label**.
- Aggregate matter risk = max over limitations, with coverage penalty when gaps
  exist (unsearched foreign cannot yield “low risk overall”).

**Human disposition**

- Disposition codes: `not_material`, `consider_ids`, `distinguish_in_remarks`,
  `needs_counsel`, `deferred`.
- IDS queue binding only after human disposition; `auto_file_blocked=true`.

### 7.2 MPEP / 37 C.F.R. conformance (G060–G080)

**Obligation catalog**

- Machine-readable obligations: id, authority cite (Title 35 / 37 CFR / MPEP),
  applicability (utility new app, response, IDS, RCE, …), evidence predicates,
  severity, fail-closed behavior.
- Seed from existing filing rule packs; expand to format (1.52, 1.71–1.75),
  duty of disclosure process (1.56 process hygiene — not materiality judgment),
  continuity (1.78), nonpublication (1.213), export/FFL diligence flags.

**Conformance engine**

- Evaluate package inventory + extracts + meta against obligations.
- Status: `satisfied | unsatisfied | unknown | human_only`.
- Attach local authority excerpts when corpus present; else `unknown` + action
  to seed authority.

**Diligence automation**

- Continuity bags, provisional title/inventorship deltas, publication posture,
  PCT/ISR evidence (extend `application_gap_closure`).
- Flags for human; never auto-confirm legal conclusions without acknowledger.

### 7.3 Continuous portfolio review (G090–G100)

**Triggers**

- New/changed IFW docs, claim amendments, priority date changes, corpus snapshot
  rebuild, scheduled interval, operator request.

**Orchestrator**

- Single entry: `review_application` / `portfolio_cli review` composing:
  export freshness → claim model → prior-art conflict → conformance → diligence
  → unified report → optional GraphRAG evidence attach.
- Exit codes: 0 ready, 1 review_required, 2 not_ready/error (never “patentable”).

### 7.4 Evaluation and release (G120, G150)

- Golden matters (synthetic + hermetic): known conflict pairs, clean packages,
  missing-authority cases, foreign-gap cases.
- Metrics: recall of planted conflicts, false-high rate, format precision,
  fail-closed rate, latency, token cost.
- Safety suite: no secret echo, no patentability phrases, no auto-file paths.

---

## 8. Success criteria (program-level)

1. For a seeded portfolio matter, one command produces a unified review report
   with conflict-risk and MPEP/CFR conformance sections, digests, and paths.
2. Planted high-overlap prior art is ranked `high` or `medium` with quotes; clean
   unrelated art stays `low` or `unknown` (never “no prior art exists”).
3. Missing MPEP/CFR authority or unsearched foreign corpus cannot yield overall
   `ready` without explicit human acceptance of named gaps.
4. Continuous scheduler re-opens review when claims or IFW change.
5. Agent supervisor can execute file-disjoint PAAR lanes in parallel with
   validation commands and merge-train integration.
6. Safety tests block patentability language, Sign/Pay/Submit hooks, and private
   body leakage on default emits.

---

## 9. Implementation order for humans (if not using supervisor)

1. Seal docs (G010) — this plan package.
2. Claim model + obligation catalog (G020, G060) in parallel.
3. Conflict engine + search orchestration + conformance (G030, G040, G070).
4. Unified orchestrator + reports (G100, G050).
5. Scheduler + dashboard (G090, G130).
6. Eval + safety gates (G120, G150).
7. Supervisor lane recipe (G140).

---

## 10. Agent supervisor usage

```bash
cd path/to/ipfs_datasets_py

# Board structure
python3 scripts/validate_paar_board.py

# Structural dry-run (6 shards, no implement; skips provider auth)
scripts/ops/patent_automated_application_review/launch_multi_lane.sh --dry-run

# Live multi-lane launch (requires feature branch + Grok/Codex auth;
# stop concurrent PATLAW supervisors first — shared protected-path lease)
git checkout -B feature/patent-automated-application-review
scripts/ops/patent_automated_application_review/launch_multi_lane.sh --create-branch

# Status
scripts/ops/patent_automated_application_review/status.sh
```

Operator package: `scripts/ops/patent_automated_application_review/README.md`.

Reviewed-board execution only: do not invent tasks outside the todo board.
Post-completion refill catalogs may add ops tasks only when explicitly configured.
Do not co-launch with live PATLAW multi-lane supervisors on the same checkout.

---

## 11. Relationship to live operator work (18654466 pilot)

The portfolio pilot on application 18654466 already exercises:

- IFW export, GraphRAG, ODP prior art, foreign gap packages, rules/format audit,
  gap closure (family/PCT/ISR, human diligence packs).

PAAR **productizes** that loop into:

- automatic conflict-risk scoring,
- full obligation-based MPEP/CFR conformance,
- continuous re-review,
- parallel agent implementation of remaining engineering work.

Pilot artifacts under `~/.local/state/.../patent_portfolio/` remain the runtime
state root; PAAR modules write new report schemas beside existing runs.

---

## 12. Document control

| Field | Value |
| --- | --- |
| Schema | `paar.plan@1` |
| Board namespace | `patent-automated-application-review-v1` |
| Status | active planning seal |
| Not legal advice | true |
| Human filing barrier | absolute |
