"""Hook scraped patent-law authorities into revision packages (decision support).

Combines:
* versioned **filing-obligation rule packs** (what a response package must
  typically contain — e.g. 37 C.F.R. 1.121 claim amendments, remarks, signature
  presence);
* **citations** parsed from the USPTO letter analysis and rule pack;
* optional **local authority corpus** excerpts (CFR / USC / MPEP text you have
  scraped or materialized under ``authority_corpus/``).

This is **not legal advice**, does not auto-rewrite claims, and never signs,
pays, or files. It produces a law-aware checklist so a human can revise
documents to fit filing rules.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    RevisionCase,
    TriggerKind,
    load_revision_case,
    save_revision_case,
)

LAW_GUIDE_SCHEMA: Final = "patlaw-revision-law-guide-v1"

LAW_GUIDE_DISCLAIMER: Final = (
    "This law guide is decision support only — not legal advice, not a "
    "completeness certification, and not a patentability determination. "
    "Filing-obligation packs and authority excerpts may be incomplete or "
    "stale. A natural person must revise documents and Sign / Pay / Submit "
    "in Patent Center. Form instructions are not controlling law."
)

# Evidence kinds from the baseline pack → revision attachment roles.
_EVIDENCE_TO_ROLES: Final[Mapping[str, tuple[str, ...]]] = {
    "claim_amendment": ("amended_claims",),
    "claims": ("amended_claims",),
    "remarks": ("remarks",),
    "specification": ("amended_specification", "substitute_specification"),
    "drawings": ("amended_drawings",),
    "ads": ("other",),
    "oath_declaration": ("declaration",),
    "signature_presence": (),  # human-only hard barrier
    "fee": ("fee_transmittal",),
    "fee_transmittal": ("fee_transmittal",),
    "ids": ("ids",),
    "amendment_transmittal": ("amendment_transmittal",),
    "identifier": (),
}

_TRIGGER_TO_SCENARIO: Final[Mapping[str, tuple[str, str]]] = {
    # trigger_kind -> (scenario, prosecution_stage)
    TriggerKind.OFFICE_ACTION_NONFINAL.value: ("office_action_response", "examination"),
    TriggerKind.OFFICE_ACTION_FINAL.value: ("after_final_response", "after_final"),
    TriggerKind.ADVISORY_ACTION.value: ("after_final_response", "after_final"),
    TriggerKind.RESTRICTION.value: ("office_action_response", "examination"),
    TriggerKind.MISSING_PARTS.value: ("missing_parts", "pre_examination"),
    TriggerKind.INCOMPLETE_APPLICATION.value: ("missing_parts", "pre_examination"),
    TriggerKind.NONCOMPLIANT_AMENDMENT.value: ("amendment", "examination"),
    TriggerKind.DEFICIENCY_NOTICE.value: ("office_action_response", "examination"),
    TriggerKind.MISC_COMMUNICATION.value: ("office_action_response", "examination"),
    TriggerKind.NOTICE_REQUIRING_RESPONSE.value: (
        "office_action_response",
        "examination",
    ),
    TriggerKind.OTHER_OUTGOING.value: ("office_action_response", "examination"),
    TriggerKind.MANUAL.value: ("office_action_response", "examination"),
}


class RevisionLawGuideError(PortfolioAutomationError):
    """Fail-closed law-guide error."""


def _trigger_scenario(trigger_kind: str) -> tuple[str, str]:
    return _TRIGGER_TO_SCENARIO.get(
        str(trigger_kind or ""),
        ("office_action_response", "examination"),
    )


def default_authority_corpus_roots(
    state_root: Path | None = None,
) -> list[Path]:
    """Ordered search roots for scraped/materialized authority text."""
    roots: list[Path] = []
    env = (os.environ.get("USPTO_AUTHORITY_CORPUS_ROOT") or "").strip()
    if env:
        roots.append(Path(env).expanduser())
    state = Path(state_root) if state_root else default_state_root()
    roots.append(state / "authority_corpus")
    # Optional shared XDG location
    xdg = Path.home() / ".local" / "share" / "ipfs_datasets_py" / "authority_corpus"
    roots.append(xdg)
    # De-dup while preserving order
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _normalize_citation_key(text: str) -> str:
    t = str(text or "").lower()
    t = t.replace("u.s.c.", "usc").replace("c.f.r.", "cfr")
    t = re.sub(r"[§¶]", " ", t)
    t = re.sub(r"[^a-z0-9.]+", "-", t)
    return t.strip("-.")


def lookup_authority_excerpt(
    citation: str,
    *,
    corpus_roots: Sequence[Path] | None = None,
    max_chars: int = 1200,
) -> dict[str, Any]:
    """Best-effort local lookup of authority text for a citation string.

    Expected layout (any root)::

        authority_corpus/
          index.json          # optional { "37-cfr-1.121": "cfr/37/1.121.txt", ... }
          cfr/37/1.121.txt
          usc/35/103.txt
          mpep/2141.txt
          **/*1.121*
    """
    roots = list(corpus_roots or default_authority_corpus_roots())
    key = _normalize_citation_key(citation)
    # Extract likely section tokens for filesystem search
    tokens: list[str] = []
    m = re.search(r"(\d+)\s*[-.]?\s*usc\s*[-.]?\s*(\d+[a-z]?)", key)
    if m:
        tokens.extend([f"{m.group(1)}-usc-{m.group(2)}", m.group(2), f"usc-{m.group(2)}"])
    m = re.search(r"(\d+)\s*[-.]?\s*cfr\s*[-.]?\s*([\d.]+)", key)
    if m:
        tokens.extend(
            [
                f"{m.group(1)}-cfr-{m.group(2)}",
                m.group(2),
                f"cfr-{m.group(2)}",
                f"1.{m.group(2).split('.')[-1]}" if "." in m.group(2) else m.group(2),
            ]
        )
    m = re.search(r"mpep\s*[-.]?\s*([\d.]+)", key)
    if m:
        tokens.extend([f"mpep-{m.group(1)}", m.group(1), f"mpep_{m.group(1)}"])
    if not tokens:
        tokens = [key]

    for root in roots:
        if not root.is_dir():
            continue
        # index.json
        index_path = root / "index.json"
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                index = {}
            if isinstance(index, Mapping):
                for cand in [key, *_normalize_variants(citation)]:
                    rel = index.get(cand) or index.get(cand.replace("-", "."))
                    if rel:
                        target = root / str(rel)
                        if target.is_file():
                            return _read_excerpt(target, citation, max_chars=max_chars, root=root)
        # recursive name search
        for token in tokens:
            if not token or len(token) < 2:
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {
                    ".txt",
                    ".md",
                    ".html",
                    ".json",
                    "",
                }:
                    # still allow .txt/.md primarily
                    if path.suffix.lower() not in {".txt", ".md", ".rst"}:
                        continue
                name = path.name.lower()
                stem = path.stem.lower()
                if token in name or token in stem or token.replace(".", "") in stem.replace(".", ""):
                    return _read_excerpt(path, citation, max_chars=max_chars, root=root)
    return {
        "citation": citation,
        "found": False,
        "path": None,
        "excerpt": None,
        "hint": (
            "No local authority text found. Place scraped CFR/USC/MPEP files under "
            f"{roots[0] if roots else 'authority_corpus/'} "
            "(see index.json mapping) or set USPTO_AUTHORITY_CORPUS_ROOT."
        ),
    }


def _normalize_variants(citation: str) -> list[str]:
    from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
        parse_patent_citations,
    )

    out = [_normalize_citation_key(citation)]
    try:
        for c in parse_patent_citations(citation):
            if c.citation_key:
                out.append(str(c.citation_key))
            if c.normalized_text:
                out.append(_normalize_citation_key(c.normalized_text))
    except Exception:
        pass
    return list(dict.fromkeys(out))


def _read_excerpt(
    path: Path, citation: str, *, max_chars: int, root: Path
) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "citation": citation,
            "found": False,
            "path": str(path),
            "excerpt": None,
            "error": str(exc),
        }
    text = raw.strip()
    # Prefer a window around the section number if present
    excerpt = text[: max(200, int(max_chars))]
    sec = re.search(r"(\d+\.\d+(?:\([a-z0-9]+\))?)", citation, re.I)
    if sec:
        needle = sec.group(1)
        idx = text.find(needle)
        if idx < 0:
            idx = text.lower().find(needle.lower())
        if idx >= 0:
            start = max(0, idx - 80)
            excerpt = text[start : start + max_chars]
    return {
        "citation": citation,
        "found": True,
        "path": str(path),
        "relative_path": str(path.relative_to(root)) if root in path.parents or path.parent == root else path.name,
        "excerpt": excerpt,
        "excerpt_len": len(excerpt),
        "source_chars": len(text),
    }


def collect_citations_from_case(case: RevisionCase) -> list[str]:
    """Gather citation surfaces from letter analysis + notes."""
    bag: list[str] = []
    la = (case.letter_analysis or {}).get("analysis") or {}
    for key in ("citations", "rejections", "objections", "response_instructions", "sections"):
        for item in la.get(key) or []:
            bag.append(str(item))
    bag.append(case.trigger.document_description or "")
    # Parse
    from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
        parse_patent_citations,
    )

    text = "\n".join(bag)
    cites = []
    try:
        for c in parse_patent_citations(text):
            if c.normalized_text:
                cites.append(c.normalized_text)
            elif c.citation_key:
                cites.append(str(c.citation_key))
    except Exception:
        pass
    # de-dup
    return list(dict.fromkeys(cites))


def resolve_filing_obligations_for_case(
    case: RevisionCase,
    *,
    application_type: str = "utility",
) -> dict[str, Any]:
    """Run FilingObligationProcessor for the case's response scenario."""
    from ipfs_datasets_py.processors.domains.uspto.analysis.filing_obligation_processor import (
        FilingObligationProcessor,
        FilingObligationRequest,
        ProsecutionStage,
    )
    from ipfs_datasets_py.processors.domains.uspto.analysis.filing_rule_packs import (
        ApplicationType,
        FilingScenario,
    )
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        DisclosureClassification,
    )

    scenario_s, stage_s = _trigger_scenario(case.trigger.kind)
    # after_final pack may gap — fall back to office_action_response
    scenarios_try = [scenario_s]
    if scenario_s == "after_final_response":
        scenarios_try.append("office_action_response")

    processor = FilingObligationProcessor()
    last: dict[str, Any] = {}
    for scen in scenarios_try:
        try:
            scenario = FilingScenario(scen)
        except ValueError:
            scenario = FilingScenario.OFFICE_ACTION_RESPONSE
        try:
            stage = ProsecutionStage(stage_s)
        except ValueError:
            stage = ProsecutionStage.EXAMINATION
        # Prefer examination for OA response rules
        if scen == "office_action_response" and stage not in {
            ProsecutionStage.EXAMINATION,
            ProsecutionStage.ANY,
        }:
            stage = ProsecutionStage.EXAMINATION

        try:
            app_type = ApplicationType(application_type)
        except ValueError:
            app_type = ApplicationType.UTILITY

        req = FilingObligationRequest(
            request_id=f"req:{case.revision_id}:{scen}",
            application_type=app_type,
            scenario=scenario,
            prosecution_stage=stage,
            matter_id=f"matter:{case.application_number}",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
        result = processor.process(req)
        payload = result.to_dict()
        matched = payload.get("matched_obligations") or []
        last = {
            "status": payload.get("status"),
            "scenario": scen,
            "prosecution_stage": stage.value
            if hasattr(stage, "value")
            else str(stage),
            "application_type": app_type.value
            if hasattr(app_type, "value")
            else str(app_type),
            "pack_id": payload.get("pack_id"),
            "pack_version": payload.get("pack_version"),
            "matched_rule_ids": payload.get("matched_rule_ids") or [],
            "matched_count": len(matched),
            "matched_obligations": matched,
            "coverage_gaps": payload.get("coverage_gaps") or [],
            "reason_codes": payload.get("reason_codes") or [],
            "disclaimer": payload.get("disclaimer"),
        }
        if matched:
            return last
    return last


def _evidence_gaps(
    matched_obligations: Sequence[Mapping[str, Any]],
    attached_roles: set[str],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for match in matched_obligations:
        rule = match.get("rule") if isinstance(match, Mapping) else None
        if not isinstance(rule, Mapping):
            continue
        rule_id = rule.get("rule_id") or match.get("rule_id")
        for ev in rule.get("required_evidence") or []:
            if not isinstance(ev, Mapping):
                continue
            kind = str(ev.get("evidence_kind") or "")
            mandatory = bool(ev.get("mandatory", True))
            conditional = ev.get("conditional_on")
            roles = _EVIDENCE_TO_ROLES.get(kind, ("other",))
            if kind == "signature_presence":
                gaps.append(
                    {
                        "rule_id": rule_id,
                        "evidence_kind": kind,
                        "description": ev.get("description"),
                        "status": "human_hard_barrier",
                        "mandatory": mandatory,
                        "note": "Sign yourself in Patent Center — never automated.",
                    }
                )
                continue
            present = any(r in attached_roles for r in roles) if roles else False
            # Conditional evidence: mark optional unless role present suggests condition met
            if conditional and not present:
                status = "conditional_unmet_or_missing"
            elif present:
                status = "present"
            elif mandatory:
                status = "missing_mandatory"
            else:
                status = "missing_optional"
            gaps.append(
                {
                    "rule_id": rule_id,
                    "evidence_kind": kind,
                    "description": ev.get("description"),
                    "expected_roles": list(roles),
                    "status": status,
                    "mandatory": mandatory,
                    "conditional_on": conditional,
                }
            )
    return gaps


def build_revision_law_guide(
    revision_id: str,
    *,
    state_root: Path | None = None,
    application_type: str = "utility",
    corpus_roots: Sequence[Path] | None = None,
    max_excerpt_chars: int = 1200,
    persist: bool = True,
) -> dict[str, Any]:
    """Build a law-aware revision guide for an open revision case."""
    root = Path(state_root) if state_root else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    corpus = list(corpus_roots) if corpus_roots is not None else default_authority_corpus_roots(root)

    obligations = resolve_filing_obligations_for_case(
        case, application_type=application_type
    )
    matched = obligations.get("matched_obligations") or []

    # Citations from letter + from matched rules
    letter_cites = collect_citations_from_case(case)
    rule_cites: list[str] = []
    obligation_cards: list[dict[str, Any]] = []
    for match in matched:
        if not isinstance(match, Mapping):
            continue
        rule = match.get("rule") if isinstance(match.get("rule"), Mapping) else {}
        cites = []
        for c in rule.get("citations") or []:
            if isinstance(c, Mapping) and c.get("citation"):
                cites.append(str(c["citation"]))
                rule_cites.append(str(c["citation"]))
        obligation_cards.append(
            {
                "rule_id": rule.get("rule_id") or match.get("rule_id"),
                "title": rule.get("title"),
                "description": rule.get("description"),
                "component": rule.get("component"),
                "mandatory": rule.get("mandatory"),
                "required_evidence": rule.get("required_evidence") or [],
                "exceptions": rule.get("exceptions") or [],
                "citations": cites,
            }
        )

    all_cites = list(dict.fromkeys([*letter_cites, *rule_cites]))
    # Always include core amendment/response rules if empty letter
    for fallback in ("37 C.F.R. 1.121", "37 C.F.R. 1.111", "37 C.F.R. 1.33"):
        if fallback not in all_cites and obligations.get("matched_count"):
            all_cites.append(fallback)

    authority_excerpts = [
        lookup_authority_excerpt(c, corpus_roots=corpus, max_chars=max_excerpt_chars)
        for c in all_cites[:30]
    ]

    # Hybrid BM25 + vector + knowledge-graph retrieval from JusticeDAO Hub indexes
    # (PATLAW public legal index track: justicedao/patent-legal-*).
    hybrid_retrieval: dict[str, Any] = {"ok": False, "hits": []}
    try:
        from ipfs_datasets_py.processors.domains.uspto.public_legal_index_client import (
            retrieve_for_revision_case,
        )

        hybrid_retrieval = retrieve_for_revision_case(case, top_k=6)
        # Prefer Hub hybrid excerpts when local authority corpus miss
        if hybrid_retrieval.get("ok"):
            for hit in hybrid_retrieval.get("hits") or []:
                cite = str(hit.get("citation") or hit.get("document_id") or "")
                if not cite or not hit.get("excerpt"):
                    continue
                # Skip if we already have a local corpus hit for same citation key
                already = any(
                    a.get("found")
                    and (
                        cite.lower() in str(a.get("citation") or "").lower()
                        or str(a.get("citation") or "").lower() in cite.lower()
                    )
                    for a in authority_excerpts
                )
                if already:
                    continue
                authority_excerpts.append(
                    {
                        "citation": cite,
                        "found": True,
                        "path": f"hf://justicedao/patent-legal-corpus#{hit.get('document_id')}",
                        "excerpt": hit.get("excerpt"),
                        "excerpt_len": len(str(hit.get("excerpt") or "")),
                        "source": "public_legal_hybrid_index",
                        "score": hit.get("score"),
                        "document_id": hit.get("document_id"),
                        "families": hit.get("family"),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        hybrid_retrieval = {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "hits": [],
        }

    attached_roles = {a.role for a in case.attachments}
    evidence = _evidence_gaps(matched, attached_roles)

    missing_mandatory = [
        e for e in evidence if e.get("status") == "missing_mandatory"
    ]
    human_barriers = [
        e for e in evidence if e.get("status") == "human_hard_barrier"
    ]

    # Practical revision tips from letter analysis + rules (content-free templates)
    tips: list[str] = []
    la = (case.letter_analysis or {}).get("analysis") or {}
    if la.get("rejections"):
        tips.append(
            "Address each rejection surface in remarks; map claim ranges to "
            "amended claim text and statutory bases cited by the examiner."
        )
    if la.get("claim_ranges"):
        tips.append(
            f"Claim ranges from letter: {la.get('claim_ranges')}. "
            "If amending, use 37 C.F.R. 1.121 mark-up conventions."
        )
    if any(e.get("evidence_kind") == "claim_amendment" for e in evidence):
        tips.append(
            "Claim amendments: include a complete claim listing with status "
            "identifiers (original/currently amended/new/canceled) per 1.121."
        )
    if any(e.get("evidence_kind") == "remarks" for e in evidence):
        tips.append(
            "Remarks must respond to each ground of rejection/objection "
            "(see 37 C.F.R. 1.111)."
        )
    tips.append(
        "HARD BARRIER: signature / certification / payment / final Submit "
        "remain human-only in Patent Center."
    )

    guide = {
        "schema": LAW_GUIDE_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "revision_id": case.revision_id,
        "application_number": case.application_number,
        "trigger": case.trigger.to_dict(),
        "scenario": obligations.get("scenario"),
        "prosecution_stage": obligations.get("prosecution_stage"),
        "application_type": application_type,
        "filing_obligations": {
            "status": obligations.get("status"),
            "pack_id": obligations.get("pack_id"),
            "pack_version": obligations.get("pack_version"),
            "matched_rule_ids": obligations.get("matched_rule_ids"),
            "matched_count": obligations.get("matched_count"),
            "coverage_gaps": obligations.get("coverage_gaps"),
            "cards": obligation_cards,
            "reason_codes": obligations.get("reason_codes"),
        },
        "letter_analysis_brief": {
            "action_kind": la.get("action_kind"),
            "rejections": la.get("rejections") or [],
            "objections": la.get("objections") or [],
            "claim_ranges": la.get("claim_ranges") or [],
            "response_instructions": la.get("response_instructions") or [],
            "period_months_from_text": la.get("period_months_from_text"),
            "citations": la.get("citations") or [],
        },
        "citations": {
            "from_letter": letter_cites,
            "from_rules": list(dict.fromkeys(rule_cites)),
            "all": all_cites,
        },
        "authority_corpus_roots": [str(p) for p in corpus],
        "authority_excerpts": authority_excerpts,
        "authority_found_count": sum(
            1 for a in authority_excerpts if a.get("found")
        ),
        "hybrid_retrieval": hybrid_retrieval,
        "package_evidence": {
            "attached_roles": sorted(attached_roles),
            "checks": evidence,
            "missing_mandatory_count": len(missing_mandatory),
            "human_barrier_count": len(human_barriers),
        },
        "revision_tips": tips,
        "next_steps": [
            "Fill missing mandatory evidence (revise attach --role …)",
            "Read authority excerpts / source URLs for cited rules",
            "Revise claims/remarks to satisfy letter rejections + 1.121/1.111",
            "revise prepare → revise filing-assist (human Sign/Pay/Submit)",
        ],
        "disclaimer": LAW_GUIDE_DISCLAIMER,
    }

    if persist and case.case_dir:
        out = Path(case.case_dir) / "law_guide.json"
        out.write_text(json.dumps(guide, indent=2, default=str) + "\n", encoding="utf-8")
        try:
            out.chmod(0o600)
        except OSError:
            pass
        guide["law_guide_path"] = str(out)
        # Store pointer on case without bloating too much
        case.notes = [
            n
            for n in case.notes
            if not str(n).startswith("law_guide:")
        ] + [f"law_guide:{out}"]
        # Keep a compact snapshot
        if not isinstance(getattr(case, "letter_analysis", None), dict):
            case.letter_analysis = {}
        # attach under case field via notes only — RevisionCase has no law_guide field
        save_revision_case(case, state_root=root)

    return guide


def seed_authority_corpus_readme(state_root: Path | None = None) -> Path:
    """Write a README explaining how to drop scraped law text for lookup."""
    root = Path(state_root) if state_root else default_state_root()
    corpus = root / "authority_corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    readme = corpus / "README.txt"
    if not readme.is_file():
        readme.write_text(
            "USPTO / patent authority corpus (local)\n"
            "========================================\n"
            "Drop scraped or official-text extracts here so `revise guide` can\n"
            "attach short excerpts next to filing-rule citations.\n\n"
            "Suggested layout:\n"
            "  index.json   # {\"37-cfr-1.121\": \"cfr/37/1.121.txt\", ...}\n"
            "  cfr/37/1.121.txt\n"
            "  usc/35/103.txt\n"
            "  mpep/2141.txt\n\n"
            "Or set env USPTO_AUTHORITY_CORPUS_ROOT to another directory.\n"
            "Never commit secrets. Authority text is public law / guidance only.\n",
            encoding="utf-8",
        )
    index = corpus / "index.json"
    if not index.is_file():
        index.write_text(
            json.dumps(
                {
                    "_comment": "Map citation keys to relative file paths under this corpus",
                    "37-cfr-1.121": "cfr/37/1.121.txt",
                    "37-cfr-1.111": "cfr/37/1.111.txt",
                    "37-cfr-1.33": "cfr/37/1.33.txt",
                    "35-usc-103": "usc/35/103.txt",
                    "35-usc-102": "usc/35/102.txt",
                    "35-usc-112": "usc/35/112.txt",
                    "mpep-2141": "mpep/2141.txt",
                    "mpep-2106": "mpep/2106.txt",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return corpus


__all__ = [
    "LAW_GUIDE_DISCLAIMER",
    "LAW_GUIDE_SCHEMA",
    "RevisionLawGuideError",
    "build_revision_law_guide",
    "collect_citations_from_case",
    "default_authority_corpus_roots",
    "lookup_authority_excerpt",
    "resolve_filing_obligations_for_case",
    "seed_authority_corpus_readme",
]
