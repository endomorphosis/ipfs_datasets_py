#!/usr/bin/env python3
"""Analyze entropy sources in formal-logic conversion artifacts.

Reads converter report JSON (and optional logic JSON-LD) and emits:
- machine-readable entropy diagnostics JSON
- markdown summary with prioritized remediation ideas
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze conversion entropy and suggest improvements.")
    p.add_argument("--report-json", required=True, help="Path to converter report.json")
    p.add_argument("--logic-jsonld", default="", help="Optional path to logic.jsonld")
    p.add_argument("--output-json", required=True, help="Where to write analysis JSON")
    p.add_argument("--output-md", required=True, help="Where to write analysis Markdown")
    return p.parse_args()


def _safe_ratio(a: int, b: int) -> float:
    return float(a / b) if b else 0.0


def _shannon_from_counts(counts: Dict[str, int]) -> Optional[float]:
    total = sum(v for v in counts.values() if v > 0)
    if total <= 0:
        return None
    ent = 0.0
    for v in counts.values():
        if v <= 0:
            continue
        p = float(v) / float(total)
        ent -= p * math.log2(p)
    return float(ent)


def _top_items(d: Dict[str, int], k: int = 8) -> List[Tuple[str, int]]:
    return sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:k]


def _collect_basic_metrics(summary: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = int(summary.get("segment_count") or len(records) or 0)
    entropy_diag = summary.get("conversion_entropy_diagnostics") or {}
    n_effective = int(entropy_diag.get("entropy_effective_segment_count") or n)

    trivial = int(entropy_diag.get("deontic_trivial_formula_count") or 0)
    weak_deontic = int(entropy_diag.get("deontic_weak_formula_count") or 0)
    weak_fol = int(entropy_diag.get("fol_weak_formula_count") or 0)
    overlong = int(entropy_diag.get("overlong_predicate_formula_count") or 0)
    no_normative_effective = entropy_diag.get("no_normative_rejections_effective")
    if no_normative_effective is None:
        no_normative = int((summary.get("theorem_rejection_reason_counts") or {}).get("no_normative_cue") or 0)
    else:
        no_normative = int(no_normative_effective)

    semantic = summary.get("semantic_similarity_by_modality") or {}
    tdfol_success = int(summary.get("tdfol_success_count") or 0)
    cec_bridge_success = int(summary.get("cec_bridge_success_count") or 0)

    tdfol_missing_effective = entropy_diag.get("tdfol_missing_effective_count")
    cec_missing_effective = entropy_diag.get("cec_bridge_missing_effective_count")
    missing_by_modality = {
        "tdfol": int(max(0, n - tdfol_success) if tdfol_missing_effective is None else tdfol_missing_effective),
        "cec_bridge": int(
            max(0, n - cec_bridge_success) if cec_missing_effective is None else cec_missing_effective
        ),
    }

    return {
        "segment_count": n,
        "deontic_trivial_count": trivial,
        "deontic_trivial_rate": _safe_ratio(trivial, n_effective),
        "deontic_weak_count": weak_deontic,
        "deontic_weak_rate": _safe_ratio(weak_deontic, n_effective),
        "fol_weak_count": weak_fol,
        "fol_weak_rate": _safe_ratio(weak_fol, n_effective),
        "overlong_predicate_count": overlong,
        "overlong_predicate_rate": _safe_ratio(overlong, n_effective),
        "no_normative_rejections": no_normative,
        "no_normative_rejection_rate": _safe_ratio(no_normative, n_effective),
        "semantic_similarity_by_modality": semantic,
        "missing_modality_counts": missing_by_modality,
        "missing_modality_rates": {k: _safe_ratio(v, n_effective) for k, v in missing_by_modality.items()},
        "deontic_operator_counts": entropy_diag.get("deontic_operator_counts") or {},
        "deontic_operator_entropy_bits": entropy_diag.get("deontic_operator_entropy_bits"),
        "deontic_operator_entropy_normalized": entropy_diag.get("deontic_operator_entropy_normalized"),
        "theorem_rejection_reason_counts": (
            entropy_diag.get("theorem_rejection_reason_counts_effective")
            or summary.get("theorem_rejection_reason_counts")
            or {}
        ),
        "theorem_rejection_entropy_bits": (
            entropy_diag.get("theorem_rejection_entropy_bits_effective")
            if entropy_diag.get("theorem_rejection_entropy_bits_effective") is not None
            else entropy_diag.get("theorem_rejection_entropy_bits")
        ),
        "heading_like_segment_count": int(entropy_diag.get("heading_like_segment_count") or 0),
        "effective_segment_count": n_effective,
    }


def _collect_kg_metrics(logic_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not logic_doc:
        return {
            "available": False,
            "assertion_nodes": 0,
            "agent_nodes": 0,
            "proposition_nodes": 0,
            "assertions_with_agent_link": 0,
            "assertions_with_proposition_link": 0,
        }

    graph = logic_doc.get("@graph") or []
    assertions = [n for n in graph if str(n.get("@id", "")).startswith("urn:logic:assertion:")]
    agents = [n for n in graph if str(n.get("@id", "")).startswith("urn:logic:agent:")]
    props = [n for n in graph if str(n.get("@id", "")).startswith("urn:logic:proposition:")]

    with_agent = sum(1 for n in assertions if n.get("mentionsAgent"))
    with_prop = sum(1 for n in assertions if n.get("aboutProposition"))

    return {
        "available": True,
        "assertion_nodes": len(assertions),
        "agent_nodes": len(agents),
        "proposition_nodes": len(props),
        "assertions_with_agent_link": with_agent,
        "assertions_with_proposition_link": with_prop,
        "assertion_agent_link_rate": _safe_ratio(with_agent, len(assertions)),
        "assertion_proposition_link_rate": _safe_ratio(with_prop, len(assertions)),
    }


def _build_recommendations(metrics: Dict[str, Any], kg: Dict[str, Any]) -> List[Dict[str, str]]:
    recs: List[Dict[str, str]] = []

    if metrics["deontic_trivial_rate"] >= 0.25:
        recs.append(
            {
                "category": "logic-rules",
                "title": "Block trivial deontic formulas earlier",
                "why": "A high O()/P()/F() rate indicates encoder collapse before theorem gating.",
                "action": "Add hard constraints: refuse empty inner propositions; require at least one grounded predicate argument before accepting deontic output.",
            }
        )

    if metrics.get("deontic_weak_rate", 0.0) >= 0.25:
        recs.append(
            {
                "category": "logic-rules",
                "title": "Enforce deontic inner-formula structure",
                "why": "Many deontic formulas include weak inner content even when not strictly O()/P()/F().",
                "action": "Require informative inner formulas (non-unary stubs, grounded predicates) and retry with focused/legal-context windows before theorem candidacy.",
            }
        )

    if metrics["fol_weak_rate"] >= 0.25:
        recs.append(
            {
                "category": "logic-rules",
                "title": "Strengthen FOL quality constraints",
                "why": "Frequent existential stubs lose actor/action/object structure.",
                "action": "Require minimum predicate arity and argument grounding, then run focused re-encode when only unary existential forms are produced.",
            }
        )

    if metrics.get("overlong_predicate_rate", 0.0) > 0.0:
        recs.append(
            {
                "category": "logic-rules",
                "title": "Block overlong packed predicates",
                "why": "Overlong predicate symbols often indicate compressed natural language rather than decomposed logical structure.",
                "action": "Enforce predicate symbol caps and decompose action spans into verb/context predicates before theorem candidacy.",
            }
        )

    sem = metrics.get("semantic_similarity_by_modality") or {}
    dsim = sem.get("deontic")
    fsim = sem.get("fol")
    if (isinstance(dsim, (float, int)) and dsim < 0.35) or (isinstance(fsim, (float, int)) and fsim < 0.35):
        recs.append(
            {
                "category": "llm-postpass",
                "title": "Add constrained NL->logic repair pass",
                "why": "Low modality similarity suggests first-pass templates are under-expressive.",
                "action": "After deterministic pass, invoke an LLM repair prompt with strict JSON schema (agent, action, object, modality, conditions) and verify by roundtrip similarity + rule checks before replacement.",
            }
        )

    if metrics.get("missing_modality_rates", {}).get("tdfol", 0.0) > 0.25:
        recs.append(
            {
                "category": "logic-system",
                "title": "Introduce typed temporal fallback",
                "why": "TDFOL non-coverage means temporal semantics are mostly absent.",
                "action": "Add deterministic temporal extraction (effective date, condition windows, event ordering) and emit typed placeholders when grammar parse fails.",
            }
        )

    tsim = sem.get("tdfol")
    bsim = sem.get("cec_bridge")
    if (isinstance(tsim, (float, int)) and tsim < 0.45) or (
        isinstance(bsim, (float, int)) and bsim < 0.4
    ):
        recs.append(
            {
                "category": "logic-system",
                "title": "Improve temporal/bridge semantic grounding",
                "why": "Low temporal and bridge similarity indicates role/event loss in fallback representations.",
                "action": "Include explicit actor/action/event arguments in TDFOL/CEC fallback formulas and require per-modality semantic floors during theorem candidacy evaluation.",
            }
        )

    if kg.get("available") and kg.get("assertion_proposition_link_rate", 0.0) < 0.6:
        recs.append(
            {
                "category": "knowledge-graph",
                "title": "Increase assertion-to-proposition linkage",
                "why": "Sparse links reduce graph query power and downstream reasoning joins.",
                "action": "Normalize proposition text (lemmatize + canonical roles) and link every assertion to canonical proposition nodes, even when theorem_candidate fails.",
            }
        )

    if not recs:
        recs.append(
            {
                "category": "stability",
                "title": "Maintain current controls",
                "why": "No dominant entropy source exceeded alert thresholds.",
                "action": "Keep strict backend and profile-specific retries, and monitor with this audit each run.",
            }
        )

    return recs


def render_md(report_name: str, metrics: Dict[str, Any], kg: Dict[str, Any], recs: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    lines.append(f"# Formal Logic Entropy Audit: {report_name}")
    lines.append("")
    lines.append("## Core Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Segments | {metrics['segment_count']} |")
    lines.append(f"| Deontic trivial rate | {metrics['deontic_trivial_rate']:.4f} |")
    lines.append(f"| FOL weak rate | {metrics['fol_weak_rate']:.4f} |")
    lines.append(f"| Overlong predicate rate | {metrics.get('overlong_predicate_rate', 0.0):.4f} |")
    lines.append(f"| Missing TDFOL rate | {metrics['missing_modality_rates'].get('tdfol', 0.0):.4f} |")
    lines.append(f"| Missing CEC bridge rate | {metrics['missing_modality_rates'].get('cec_bridge', 0.0):.4f} |")
    lines.append("")

    lines.append("## Semantic Means")
    lines.append("")
    lines.append("| Modality | Similarity |")
    lines.append("|---|---:|")
    for k, v in sorted((metrics.get("semantic_similarity_by_modality") or {}).items()):
        lines.append(f"| {k} | {v if v is not None else 'n/a'} |")
    lines.append("")

    rr = metrics.get("theorem_rejection_reason_counts") or {}
    lines.append("## Top Rejection Reasons")
    lines.append("")
    lines.append("| Reason | Count |")
    lines.append("|---|---:|")
    for reason, count in _top_items(rr, 10):
        lines.append(f"| {reason} | {count} |")
    lines.append("")

    lines.append("## Knowledge Graph Coverage")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| KG available | {kg.get('available')} |")
    lines.append(f"| Assertion nodes | {kg.get('assertion_nodes')} |")
    lines.append(f"| Agent nodes | {kg.get('agent_nodes')} |")
    lines.append(f"| Proposition nodes | {kg.get('proposition_nodes')} |")
    lines.append(f"| Assertion->Agent link rate | {kg.get('assertion_agent_link_rate', 0.0):.4f} |")
    lines.append(f"| Assertion->Proposition link rate | {kg.get('assertion_proposition_link_rate', 0.0):.4f} |")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    for i, rec in enumerate(recs, start=1):
        lines.append(f"{i}. [{rec['category']}] {rec['title']}")
        lines.append(f"   - Why: {rec['why']}")
        lines.append(f"   - Action: {rec['action']}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    report_path = Path(args.report_json)
    logic_path = Path(args.logic_jsonld) if args.logic_jsonld else None

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("summary") or {}
    records = report.get("records") or []

    logic_doc = None
    if logic_path and logic_path.exists():
        logic_doc = json.loads(logic_path.read_text(encoding="utf-8"))

    metrics = _collect_basic_metrics(summary, records)
    kg = _collect_kg_metrics(logic_doc)
    recs = _build_recommendations(metrics, kg)

    out = {
        "report_json": str(report_path),
        "logic_jsonld": str(logic_path) if logic_path else None,
        "metrics": metrics,
        "knowledge_graph": kg,
        "recommendations": recs,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(report_path.parent.name, metrics, kg, recs), encoding="utf-8")

    print(json.dumps({
        "output_json": str(out_json),
        "output_md": str(out_md),
        "segment_count": metrics.get("segment_count", 0),
        "recommendation_count": len(recs),
    }, indent=2))


if __name__ == "__main__":
    main()
