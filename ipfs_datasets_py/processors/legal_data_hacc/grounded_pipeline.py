#!/usr/bin/env python3
"""Run a grounded HACC evidence workflow plus adversarial optimization."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[5]
COMPLAINT_GENERATOR_ROOT = Path(__file__).resolve().parents[4]
HACC_DEFAULT_PROVIDER = "codex"
HACC_DEFAULT_MODEL = "gpt-5.3-codex"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(COMPLAINT_GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPLAINT_GENERATOR_ROOT))


from hacc_adversarial_runner import run_hacc_adversarial_batch

from .complaint_manager import complaint_manager_interfaces
from .research_engine import HACCResearchEngine


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_json_if_exists(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _grounding_overview(grounding_bundle: Dict[str, Any], upload_report: Dict[str, Any]) -> Dict[str, Any]:
    anchor_sections = [str(item) for item in list(grounding_bundle.get("anchor_sections") or []) if str(item)]
    anchor_passages = [dict(item) for item in list(grounding_bundle.get("anchor_passages") or []) if isinstance(item, dict)]
    upload_candidates = [dict(item) for item in list(grounding_bundle.get("upload_candidates") or []) if isinstance(item, dict)]
    mediator_packets = [dict(item) for item in list(grounding_bundle.get("mediator_evidence_packets") or []) if isinstance(item, dict)]
    uploads = [dict(item) for item in list(upload_report.get("uploads") or []) if isinstance(item, dict)]

    top_titles: list[str] = []
    for item in upload_candidates[:3]:
        title = str(item.get("title") or item.get("relative_path") or item.get("source_path") or "").strip()
        if title and title not in top_titles:
            top_titles.append(title)

    return {
        "evidence_summary": str(grounding_bundle.get("evidence_summary") or "").strip(),
        "anchor_sections": anchor_sections,
        "anchor_passage_count": len(anchor_passages),
        "upload_candidate_count": len(upload_candidates),
        "mediator_packet_count": len(mediator_packets),
        "uploaded_evidence_count": int(upload_report.get("upload_count") or len(uploads) or 0),
        "top_documents": top_titles,
    }


def _build_adversarial_seed_complaints(
    *,
    grounding_bundle: Dict[str, Any],
    grounding_overview: Dict[str, Any],
    query: str,
    claim_type: str,
    count: int,
) -> List[Dict[str, Any]]:
    synthetic_prompts = dict(grounding_bundle.get("synthetic_prompts") or {})
    upload_candidates = [
        dict(item)
        for item in list(grounding_bundle.get("upload_candidates") or [])
        if isinstance(item, dict)
    ]
    anchor_passages = [
        dict(item)
        for item in list(grounding_bundle.get("anchor_passages") or [])
        if isinstance(item, dict)
    ]
    mediator_packets = [
        dict(item)
        for item in list(grounding_bundle.get("mediator_evidence_packets") or [])
        if isinstance(item, dict)
    ]
    anchor_sections = [str(item) for item in list(grounding_bundle.get("anchor_sections") or []) if str(item)]
    top_documents = [str(item) for item in list(grounding_overview.get("top_documents") or []) if str(item)]
    evidence_summary = str(grounding_bundle.get("evidence_summary") or grounding_overview.get("evidence_summary") or "").strip()
    description = evidence_summary or f"Grounded HACC evidence for '{query}'"

    base_seed = {
        "template_id": f"hacc-grounded::{claim_type}",
        "type": claim_type,
        "category": "hacc_grounded",
        "description": description,
        "summary": description,
        "key_facts": {
            "incident_summary": description,
            "evidence_query": query,
            "evidence_summary": evidence_summary,
            "anchor_sections": anchor_sections,
            "anchor_passages": anchor_passages,
            "supporting_evidence": upload_candidates,
            "mediator_evidence_packets": mediator_packets,
            "supporting_documents": top_documents,
            "synthetic_prompts": synthetic_prompts,
            "search_summary": dict(grounding_bundle.get("search_summary") or {}),
            "external_research_bundle": dict(grounding_bundle.get("external_research_bundle") or {}),
            "chronology_analysis": dict(grounding_bundle.get("chronology_analysis") or {}),
            "claim_support_temporal_handoff": dict(grounding_bundle.get("claim_support_temporal_handoff") or {}),
            "drafting_readiness": dict(grounding_bundle.get("drafting_readiness") or {}),
            "document_generation_handoff": dict(grounding_bundle.get("document_generation_handoff") or {}),
            "workflow_phase_priorities": list(synthetic_prompts.get("workflow_phase_priorities") or []),
            "blocker_objectives": list(synthetic_prompts.get("blocker_objectives") or []),
            "extraction_targets": list(synthetic_prompts.get("extraction_targets") or []),
        },
    }

    seed_count = max(1, int(count or 1))
    return [
        {
            **base_seed,
            "template_id": f"{base_seed['template_id']}::{index + 1}",
        }
        for index in range(seed_count)
    ]


def _default_grounding_request(hacc_preset: str) -> Dict[str, str]:
    try:
        from adversarial_harness.hacc_evidence import get_hacc_query_specs
    except Exception:
        return {
            "query": hacc_preset.replace("_", " "),
            "claim_type": "housing_discrimination",
        }

    specs = get_hacc_query_specs(preset=hacc_preset)
    if not specs:
        return {
            "query": hacc_preset.replace("_", " "),
            "claim_type": "housing_discrimination",
        }
    first = dict(specs[0] or {})
    return {
        "query": str(first.get("query") or hacc_preset.replace("_", " ")),
        "claim_type": str(first.get("type") or "housing_discrimination"),
    }


def _load_synthesis_module() -> Any:
    scripts_dir = COMPLAINT_GENERATOR_ROOT / "scripts"
    scripts_dir_str = str(scripts_dir)
    if scripts_dir_str not in sys.path:
        sys.path.insert(0, scripts_dir_str)
    return importlib.import_module("synthesize_hacc_complaint")


def _run_complaint_synthesis(
    *,
    grounded_run_dir: Path,
    filing_forum: str,
    preset: str,
    completed_intake_worksheet: str | None = None,
) -> Dict[str, Any]:
    synthesis_module = _load_synthesis_module()
    adversarial_results_path = grounded_run_dir / "adversarial" / "adversarial_results.json"
    output_dir = grounded_run_dir / "complaint_synthesis"
    argv = [
        "--results-json",
        str(adversarial_results_path),
        "--grounded-run-dir",
        str(grounded_run_dir),
        "--filing-forum",
        filing_forum,
        "--output-dir",
        str(output_dir),
    ]
    if preset:
        argv.extend(["--preset", preset])
    if completed_intake_worksheet:
        argv.extend(["--completed-intake-worksheet", completed_intake_worksheet])
    synthesis_module.main(argv)
    return {
        "output_dir": str(output_dir),
        "draft_complaint_package_json": str(output_dir / "draft_complaint_package.json"),
        "draft_complaint_package_md": str(output_dir / "draft_complaint_package.md"),
        "intake_follow_up_worksheet_json": str(output_dir / "intake_follow_up_worksheet.json"),
        "intake_follow_up_worksheet_md": str(output_dir / "intake_follow_up_worksheet.md"),
    }


def _build_synthesis_skip_summary(*, reason: str, detail: str = "") -> Dict[str, Any]:
    return {
        "status": "skipped",
        "reason": reason,
        "detail": detail,
        "output_dir": "",
        "draft_complaint_package_json": "",
        "draft_complaint_package_md": "",
        "intake_follow_up_worksheet_json": "",
        "intake_follow_up_worksheet_md": "",
    }


def _write_grounding_artifacts(
    *,
    output_root: Path,
    grounding_bundle: Dict[str, Any],
    upload_report: Dict[str, Any],
    grounding_path: Path,
    grounding_overview_path: Path,
    anchor_passages_path: Path,
    upload_candidates_path: Path,
    mediator_packets_path: Path,
    prompts_path: Path,
    retrieval_support_path: Path,
    external_research_path: Path,
    interfaces_path: Path,
    upload_path: Path,
) -> Dict[str, Any]:
    grounding_overview = _json_safe(_grounding_overview(grounding_bundle, upload_report))
    grounding_path.write_text(json.dumps(grounding_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    grounding_overview_path.write_text(json.dumps(grounding_overview, ensure_ascii=False, indent=2), encoding="utf-8")
    anchor_passages_path.write_text(
        json.dumps(grounding_bundle.get("anchor_passages", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    upload_candidates_path.write_text(
        json.dumps(grounding_bundle.get("upload_candidates", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    mediator_packets_path.write_text(
        json.dumps(grounding_bundle.get("mediator_evidence_packets", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prompts_path.write_text(
        json.dumps(grounding_bundle.get("synthetic_prompts", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    retrieval_support_path.write_text(
        json.dumps(grounding_bundle.get("retrieval_support_bundle", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    external_research_path.write_text(
        json.dumps(grounding_bundle.get("external_research_bundle", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    interfaces_path.write_text(
        json.dumps(
            grounding_bundle.get("complaint_manager_interfaces", complaint_manager_interfaces()),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    upload_path.write_text(json.dumps(upload_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return grounding_overview


def _write_pipeline_progress(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def run_hacc_grounded_pipeline(
    *,
    output_dir: str | Path,
    query: Optional[str] = None,
    hacc_preset: str = "core_hacc_policies",
    claim_type: Optional[str] = None,
    top_k: int = 5,
    demo: bool = False,
    num_sessions: int = 3,
    max_turns: int = 4,
    max_parallel: int = 1,
    use_hacc_vector_search: bool = False,
    hacc_search_mode: str = "package",
    config_path: Optional[str] = None,
    backend_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    synthesize_complaint: bool = False,
    filing_forum: str = "court",
    completed_intake_worksheet: Optional[str] = None,
    reuse_existing_artifacts: bool = False,
) -> Dict[str, Any]:
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    resolved_provider = str(provider or "").strip() or HACC_DEFAULT_PROVIDER
    resolved_model = str(model or "").strip() or HACC_DEFAULT_MODEL

    default_request = _default_grounding_request(hacc_preset)
    grounding_query = str(query or default_request["query"])
    resolved_claim_type = str(claim_type or default_request["claim_type"] or "housing_discrimination")

    grounding_path = output_root / "grounding_bundle.json"
    grounding_overview_path = output_root / "grounding_overview.json"
    anchor_passages_path = output_root / "anchor_passages.json"
    upload_candidates_path = output_root / "upload_candidates.json"
    mediator_packets_path = output_root / "mediator_evidence_packets.json"
    prompts_path = output_root / "synthetic_prompts.json"
    retrieval_support_path = output_root / "retrieval_support_bundle.json"
    external_research_path = output_root / "external_research_bundle.json"
    interfaces_path = output_root / "complaint_manager_interfaces.json"
    upload_path = output_root / "evidence_upload_report.json"
    adversarial_path = output_root / "adversarial_summary.json"
    summary_path = output_root / "run_summary.json"
    progress_path = output_root / "progress.json"

    _write_pipeline_progress(
        progress_path,
        {
            "status": "initializing",
            "timestamp": datetime.now(UTC).isoformat(),
            "output_dir": str(output_root),
            "grounding_query": grounding_query,
            "reuse_existing_artifacts": bool(reuse_existing_artifacts),
        },
    )

    grounding_bundle = _load_json_if_exists(grounding_path) if reuse_existing_artifacts else None
    upload_report = _load_json_if_exists(upload_path) if reuse_existing_artifacts else None

    if grounding_bundle is None or upload_report is None:
        _write_pipeline_progress(
            progress_path,
            {
                "status": "building_grounding_bundle",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )
        engine = HACCResearchEngine(repo_root=REPO_ROOT)
        grounding_bundle = engine.build_grounding_bundle(
            grounding_query,
            top_k=top_k,
            claim_type=resolved_claim_type,
            search_mode=hacc_search_mode,
            use_vector=use_hacc_vector_search,
        )
        _write_pipeline_progress(
            progress_path,
            {
                "status": "grounding_bundle_ready",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )
        _write_pipeline_progress(
            progress_path,
            {
                "status": "uploading_evidence",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )
        upload_report = engine.simulate_evidence_upload(
            grounding_query,
            top_k=top_k,
            claim_type=resolved_claim_type,
            user_id="hacc-grounded-pipeline",
            search_mode=hacc_search_mode,
            use_vector=use_hacc_vector_search,
            db_dir=output_root / "mediator_state",
        )
        grounding_bundle = _json_safe(grounding_bundle)
        upload_report = _json_safe(upload_report)
        grounding_overview = _write_grounding_artifacts(
            output_root=output_root,
            grounding_bundle=grounding_bundle,
            upload_report=upload_report,
            grounding_path=grounding_path,
            grounding_overview_path=grounding_overview_path,
            anchor_passages_path=anchor_passages_path,
            upload_candidates_path=upload_candidates_path,
            mediator_packets_path=mediator_packets_path,
            prompts_path=prompts_path,
            retrieval_support_path=retrieval_support_path,
            external_research_path=external_research_path,
            interfaces_path=interfaces_path,
            upload_path=upload_path,
        )
    else:
        grounding_bundle = _json_safe(grounding_bundle)
        upload_report = _json_safe(upload_report)
        grounding_overview = _json_safe(_grounding_overview(grounding_bundle, upload_report))
        _write_pipeline_progress(
            progress_path,
            {
                "status": "reused_grounding_and_upload",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )

    adversarial_seed_complaints = _build_adversarial_seed_complaints(
        grounding_bundle=grounding_bundle,
        grounding_overview=grounding_overview,
        query=grounding_query,
        claim_type=resolved_claim_type,
        count=num_sessions,
    )

    adversarial_summary = _load_json_if_exists(adversarial_path) if reuse_existing_artifacts else None
    if adversarial_summary is None and reuse_existing_artifacts:
        adversarial_summary = _load_json_if_exists(output_root / "adversarial" / "run_summary.json")
    if adversarial_summary is None:
        _write_pipeline_progress(
            progress_path,
            {
                "status": "running_adversarial_batch",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )
        adversarial_summary = run_hacc_adversarial_batch(
            output_dir=output_root / "adversarial",
            num_sessions=num_sessions,
            max_turns=max_turns,
            max_parallel=max_parallel,
            hacc_preset=hacc_preset,
            hacc_count=top_k,
            use_hacc_vector_search=use_hacc_vector_search,
            hacc_search_mode=hacc_search_mode,
            demo=demo,
            config_path=config_path,
            backend_id=backend_id,
            provider=resolved_provider,
            model=resolved_model,
            seed_complaints=adversarial_seed_complaints,
        )
    else:
        _write_pipeline_progress(
            progress_path,
            {
                "status": "reused_adversarial_summary",
                "timestamp": datetime.now(UTC).isoformat(),
                "output_dir": str(output_root),
                "grounding_query": grounding_query,
                "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            },
        )
    adversarial_summary = _json_safe(adversarial_summary)
    grounding_overview = _write_grounding_artifacts(
        output_root=output_root,
        grounding_bundle=grounding_bundle,
        upload_report=upload_report,
        grounding_path=grounding_path,
        grounding_overview_path=grounding_overview_path,
        anchor_passages_path=anchor_passages_path,
        upload_candidates_path=upload_candidates_path,
        mediator_packets_path=mediator_packets_path,
        prompts_path=prompts_path,
        retrieval_support_path=retrieval_support_path,
        external_research_path=external_research_path,
        interfaces_path=interfaces_path,
        upload_path=upload_path,
    )
    adversarial_path.write_text(json.dumps(adversarial_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    synthesis_summary: Dict[str, Any] = {}
    if synthesize_complaint:
        successful_sessions = int(
            ((adversarial_summary.get("statistics") if isinstance(adversarial_summary, dict) else {}) or {}).get(
                "successful_sessions",
                0,
            )
            or 0
        )
        if successful_sessions <= 0:
            synthesis_summary = _build_synthesis_skip_summary(
                reason="no_successful_adversarial_sessions",
                detail="Complaint synthesis was skipped because the adversarial batch produced no successful sessions.",
            )
            _write_pipeline_progress(
                progress_path,
                {
                    "status": "complaint_synthesis_skipped",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "output_dir": str(output_root),
                    "grounding_query": grounding_query,
                    "reuse_existing_artifacts": bool(reuse_existing_artifacts),
                    "reason": synthesis_summary["reason"],
                },
            )
        else:
            _write_pipeline_progress(
                progress_path,
                {
                    "status": "running_complaint_synthesis",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "output_dir": str(output_root),
                    "grounding_query": grounding_query,
                    "reuse_existing_artifacts": bool(reuse_existing_artifacts),
                },
            )
            try:
                synthesis_summary = _json_safe(
                    _run_complaint_synthesis(
                        grounded_run_dir=output_root,
                        filing_forum=filing_forum,
                        preset=hacc_preset,
                        completed_intake_worksheet=completed_intake_worksheet,
                    )
                )
            except ValueError as exc:
                if "No successful session with critic_score found in results payload" not in str(exc):
                    raise
                synthesis_summary = _build_synthesis_skip_summary(
                    reason="missing_successful_session_with_critic_score",
                    detail=str(exc),
                )
                _write_pipeline_progress(
                    progress_path,
                    {
                        "status": "complaint_synthesis_skipped",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "output_dir": str(output_root),
                        "grounding_query": grounding_query,
                        "reuse_existing_artifacts": bool(reuse_existing_artifacts),
                        "reason": synthesis_summary["reason"],
                    },
                )

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "grounding_query": grounding_query,
        "claim_type": resolved_claim_type,
        "hacc_preset": hacc_preset,
        "use_hacc_vector_search": bool(use_hacc_vector_search),
        "hacc_search_mode": hacc_search_mode,
        "reuse_existing_artifacts": bool(reuse_existing_artifacts),
        "inputs": {
            "output_dir": str(output_root),
            "grounding_query": grounding_query,
            "claim_type": resolved_claim_type,
            "hacc_preset": hacc_preset,
            "top_k": int(top_k),
            "num_sessions": int(num_sessions),
            "max_turns": int(max_turns),
            "max_parallel": int(max_parallel),
            "use_hacc_vector_search": bool(use_hacc_vector_search),
            "hacc_search_mode": hacc_search_mode,
            "demo": bool(demo),
            "provider": provider,
            "model": model,
            "synthesize_complaint": bool(synthesize_complaint),
            "filing_forum": filing_forum,
            "completed_intake_worksheet": completed_intake_worksheet or "",
            "reuse_existing_artifacts": bool(reuse_existing_artifacts),
        },
        "search_summary": {
            "grounding": grounding_bundle.get("search_summary", {}),
            "evidence_upload": upload_report.get("search_summary", {}),
            "adversarial": adversarial_summary.get("search_summary", {}),
        },
        "complaint_manager_interfaces": grounding_bundle.get(
            "complaint_manager_interfaces", complaint_manager_interfaces()
        ),
        "grounding_overview": grounding_overview,
        "grounding": grounding_bundle,
        "evidence_upload": upload_report,
        "adversarial": adversarial_summary,
        "complaint_synthesis": synthesis_summary,
        "artifacts": {
            "output_dir": str(output_root),
            "grounding_bundle_json": str(grounding_path),
            "grounding_overview_json": str(grounding_overview_path),
            "anchor_passages_json": str(anchor_passages_path),
            "upload_candidates_json": str(upload_candidates_path),
            "mediator_evidence_packets_json": str(mediator_packets_path),
            "synthetic_prompts_json": str(prompts_path),
            "retrieval_support_bundle_json": str(retrieval_support_path),
            "external_research_bundle_json": str(external_research_path),
            "complaint_manager_interfaces_json": str(interfaces_path),
            "evidence_upload_report_json": str(upload_path),
            "adversarial_summary_json": str(adversarial_path),
            "adversarial_output_dir": str(output_root / "adversarial"),
            "complaint_synthesis_dir": synthesis_summary.get("output_dir", ""),
            "draft_complaint_package_json": synthesis_summary.get("draft_complaint_package_json", ""),
            "draft_complaint_package_md": synthesis_summary.get("draft_complaint_package_md", ""),
            "intake_follow_up_worksheet_json": synthesis_summary.get("intake_follow_up_worksheet_json", ""),
            "intake_follow_up_worksheet_md": synthesis_summary.get("intake_follow_up_worksheet_md", ""),
            "progress_json": str(progress_path),
            "complaint_synthesis": {
                "output_dir": synthesis_summary.get("output_dir", ""),
                "draft_complaint_package_json": synthesis_summary.get("draft_complaint_package_json", ""),
                "draft_complaint_package_md": synthesis_summary.get("draft_complaint_package_md", ""),
                "intake_follow_up_worksheet_json": synthesis_summary.get("intake_follow_up_worksheet_json", ""),
                "intake_follow_up_worksheet_md": synthesis_summary.get("intake_follow_up_worksheet_md", ""),
            },
        },
    }
    summary = _json_safe(summary)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_pipeline_progress(
        progress_path,
        {
            "status": "completed",
            "timestamp": datetime.now(UTC).isoformat(),
            "output_dir": str(output_root),
            "grounding_query": grounding_query,
            "reuse_existing_artifacts": bool(reuse_existing_artifacts),
            "run_summary_json": str(summary_path),
        },
    )
    return summary


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run repository-grounded evidence upload simulation plus HACC adversarial optimization.",
    )
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "research_results" / "grounded_runs" / _timestamp()))
    parser.add_argument("--query", default=None, help="Optional explicit grounding query. Defaults to the first query in the selected preset.")
    parser.add_argument("--hacc-preset", default="core_hacc_policies")
    parser.add_argument("--claim-type", default=None, help="Optional explicit claim type for upload simulation.")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum number of repository evidence files to upload.")
    parser.add_argument("--num-sessions", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--use-hacc-vector-search", action="store_true")
    parser.add_argument(
        "--hacc-search-mode",
        choices=("auto", "lexical", "hybrid", "vector", "package"),
        default="package",
        help="Search strategy used for HACC evidence retrieval during the adversarial batch.",
    )
    parser.add_argument("--demo", action="store_true", help="Use deterministic demo backends for the adversarial run.")
    parser.add_argument("--config", default=None, help="Optional complaint-generator config JSON.")
    parser.add_argument("--backend-id", default=None, help="Optional backend id from the selected config.")
    parser.add_argument(
        "--provider",
        default=HACC_DEFAULT_PROVIDER,
        help=f"LLM router provider override for the adversarial batch. Defaults to {HACC_DEFAULT_PROVIDER}.",
    )
    parser.add_argument("--model", default=HACC_DEFAULT_MODEL)
    parser.add_argument("--synthesize-complaint", action="store_true", help="Run complaint synthesis after the grounded adversarial batch completes.")
    parser.add_argument("--filing-forum", default="court", choices=("court", "hud", "state_agency"))
    parser.add_argument("--completed-intake-worksheet", default=None, help="Optional completed intake_follow_up_worksheet.json to merge into synthesis.")
    parser.add_argument("--reuse-existing-artifacts", action="store_true", help="Reuse existing grounding/adversarial artifacts in the output directory before rerunning expensive stages.")
    parser.add_argument("--json", action="store_true", help="Print the full workflow summary JSON.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = create_parser().parse_args(argv)
    summary = run_hacc_grounded_pipeline(
        output_dir=args.output_dir,
        query=args.query,
        hacc_preset=args.hacc_preset,
        claim_type=args.claim_type,
        top_k=args.top_k,
        demo=args.demo,
        num_sessions=args.num_sessions,
        max_turns=args.max_turns,
        max_parallel=args.max_parallel,
        use_hacc_vector_search=args.use_hacc_vector_search,
        hacc_search_mode=args.hacc_search_mode,
        config_path=args.config,
        backend_id=args.backend_id,
        provider=args.provider,
        model=args.model,
        synthesize_complaint=args.synthesize_complaint,
        filing_forum=args.filing_forum,
        completed_intake_worksheet=args.completed_intake_worksheet,
        reuse_existing_artifacts=args.reuse_existing_artifacts,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Output directory: {summary['artifacts']['output_dir']}")
        print(f"Grounding query: {summary['grounding_query']}")
        grounding_search = summary.get("search_summary", {}).get("grounding", {})
        upload_search = summary.get("search_summary", {}).get("evidence_upload", {})
        adversarial_search = summary.get("search_summary", {}).get("adversarial", {})
        if grounding_search:
            print(
                "Grounding search mode: "
                f"requested={grounding_search.get('requested_search_mode', '')} "
                f"effective={grounding_search.get('effective_search_mode', '')}"
            )
            if grounding_search.get("fallback_note"):
                print(f"Grounding search fallback: {grounding_search['fallback_note']}")
        if upload_search:
            print(
                "Evidence upload search mode: "
                f"requested={upload_search.get('requested_search_mode', '')} "
                f"effective={upload_search.get('effective_search_mode', '')}"
            )
        if adversarial_search:
            print(
                "Adversarial search mode: "
                f"requested={adversarial_search.get('requested_search_mode', '')} "
                f"effective={adversarial_search.get('effective_search_mode', '')}"
            )
            if adversarial_search.get("fallback_note"):
                print(f"Adversarial search fallback: {adversarial_search['fallback_note']}")
        print(f"Uploaded evidence count: {summary['evidence_upload']['upload_count']}")
        print(f"Adversarial output directory: {summary['artifacts']['adversarial_output_dir']}")
        print(f"Synthetic prompts: {summary['artifacts']['synthetic_prompts_json']}")
        if summary["artifacts"].get("draft_complaint_package_json"):
            print(f"Draft complaint package: {summary['artifacts']['draft_complaint_package_json']}")
        if summary["artifacts"].get("intake_follow_up_worksheet_json"):
            print(f"Intake worksheet: {summary['artifacts']['intake_follow_up_worksheet_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
