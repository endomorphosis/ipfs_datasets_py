from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from .complaint_manager import (
    COMPLAINT_GENERATOR_ROOT,
    complaint_manager_interfaces,
    ensure_complaint_generator_on_path,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
if COMPLAINT_GENERATOR_ROOT.exists():
    ensure_complaint_generator_on_path()

try:
    from integrations.ipfs_datasets import (
        DOCUMENTS_AVAILABLE,
        DOCUMENTS_ERROR,
        EMBEDDINGS_AVAILABLE,
        VECTOR_STORE_AVAILABLE,
        VECTOR_STORE_ERROR,
        create_vector_index,
        discover_seeded_commoncrawl,
        get_ipfs_datasets_capabilities,
        ingest_local_document,
        scrape_web_content,
        search_brave_web,
        search_multi_engine_web,
        search_vector_index,
        summarize_ipfs_datasets_capability_report,
    )
    from integrations.ipfs_datasets.graphs import extract_graph_from_text
    from integrations.ipfs_datasets.legal import (
        LEGAL_SCRAPERS_AVAILABLE,
        LEGAL_SCRAPERS_ERROR,
        search_federal_register,
        search_recap_documents,
        search_us_code,
    )
    from adversarial_harness.hacc_evidence import (
        ANCHOR_SECTION_PATTERNS as CG_ANCHOR_SECTION_PATTERNS,
        _classify_anchor_sections as classify_anchor_sections,
    )
    from complaint_phases.intake_case_file import _build_temporal_context as build_shared_temporal_context
    from complaint_phases.intake_case_file import build_timeline_consistency_summary
    from mediator.integrations.contracts import NormalizedRetrievalRecord
    from mediator.integrations.retrieval_orchestrator import RetrievalOrchestrator
except Exception as exc:  # pragma: no cover - exercised through fallback behavior
    DOCUMENTS_AVAILABLE = False
    DOCUMENTS_ERROR = str(exc)
    EMBEDDINGS_AVAILABLE = False
    VECTOR_STORE_AVAILABLE = False
    VECTOR_STORE_ERROR = str(exc)
    create_vector_index = None
    discover_seeded_commoncrawl = None
    get_ipfs_datasets_capabilities = None
    ingest_local_document = None
    scrape_web_content = None
    search_brave_web = None
    search_multi_engine_web = None
    search_vector_index = None
    summarize_ipfs_datasets_capability_report = None
    extract_graph_from_text = None
    LEGAL_SCRAPERS_AVAILABLE = False
    LEGAL_SCRAPERS_ERROR = str(exc)
    search_federal_register = None
    search_recap_documents = None
    search_us_code = None
    CG_ANCHOR_SECTION_PATTERNS = {
        "grievance_hearing": (
            "grievance hearing",
            "informal hearing",
            "impartial person",
            "hearing process",
            "hearing procedures",
            "request a grievance hearing",
        ),
        "appeal_rights": (
            "appeal",
            "review",
            "right to appeal",
            "right to request",
            "due process",
            "due process rights",
            "final decision",
            "written notice",
        ),
        "reasonable_accommodation": ("reasonable accommodation", "person with a disability", "disability", "accommodation"),
        "adverse_action": (
            "termination",
            "termination decision",
            "denial",
            "adverse action",
            "admission",
            "occupancy",
            "terminate assistance",
            "discontinued",
            "notice of adverse action",
        ),
        "selection_criteria": ("selection", "screening", "criteria", "evaluation", "prioritization"),
    }

    def classify_anchor_sections(snippet: str) -> List[str]:
        normalized = str(snippet or "").strip().lower()
        labels: List[str] = []
        for label, patterns in CG_ANCHOR_SECTION_PATTERNS.items():
            if any(pattern in normalized for pattern in patterns):
                labels.append(label)
        return labels or ["general_policy"]

    build_shared_temporal_context = None
    build_timeline_consistency_summary = None
    NormalizedRetrievalRecord = None
    RetrievalOrchestrator = None

    INTEGRATION_IMPORT_ERROR = str(exc)
else:
    INTEGRATION_IMPORT_ERROR = None


REPOSITORY_EVIDENCE_EXTENSIONS = {".html", ".htm", ".json", ".md", ".txt"}
REPOSITORY_EVIDENCE_RECURSIVE_DIRS = (
    "correspondances",
    "research_data",
    "research_results",
    "state",
)
REPOSITORY_EVIDENCE_SKIP_PARTS = {
    ".git",
    "__pycache__",
    "adversarial_runs",
    "complaint-generator",
    "grounded_runs",
    "hacc_website",
    "search_reports",
    "search_indexes",
}
REPOSITORY_EVIDENCE_MAX_BYTES = 2_000_000
MAX_TIMELINE_EXTRACTION_CHARS = 8_000
MAX_SHARED_TEMPORAL_SENTENCE_CHARS = 400
GROUNDING_WORKFLOW_PHASE_PRIORITIES = (
    "intake_questioning",
    "evidence_upload",
    "graph_analysis",
    "document_generation",
)
ANCHOR_SECTION_BLOCKER_OBJECTIVES = {
    "grievance_hearing": ("hearing_request_timing", "exact_dates"),
    "appeal_rights": ("response_dates", "exact_dates"),
    "reasonable_accommodation": ("staff_names_titles", "documents"),
    "adverse_action": ("adverse_action_specificity", "exact_dates", "causation_sequence"),
    "selection_criteria": ("staff_names_titles", "documents"),
}
ANCHOR_SECTION_EXTRACTION_TARGETS = {
    "grievance_hearing": ("hearing_process", "timeline_anchors"),
    "appeal_rights": ("response_timeline", "timeline_anchors"),
    "reasonable_accommodation": ("actor_role_mapping", "document_identifier_mapping"),
    "adverse_action": ("adverse_action_definition", "timeline_anchors", "actor_role_mapping"),
    "selection_criteria": ("actor_role_mapping", "document_identifier_mapping"),
}
ANCHOR_SECTION_TEMPORAL_PROOF_OBJECTIVES = {
    "grievance_hearing": ("show hearing request preceded HACC response",),
    "appeal_rights": ("show notice and response timeline",),
    "adverse_action": ("show adverse action chronology", "show causation sequence"),
    "reasonable_accommodation": ("show accommodation request handling sequence",),
}
EXTERNAL_RESEARCH_HINTS_BY_CLAIM = {
    "housing_discrimination": {
        "web": (
            "fair housing retaliation",
            "HUD informal hearing",
            "voucher termination notice",
            "public housing grievance procedure",
        ),
        "legal": (
            "Fair Housing Act retaliation",
            "24 C.F.R. 982.555 informal hearing",
            "24 C.F.R. part 966 grievance procedures",
            "42 U.S.C. 1437d grievance procedure",
            "42 U.S.C. 1437d(k) grievance procedure",
            "42 U.S.C. 3604 fair housing retaliation",
            "42 U.S.C. 3617 fair housing retaliation coercion intimidation interference",
        ),
    },
    "retaliation": {
        "web": (
            "protected activity adverse action",
            "complaint retaliation timeline",
        ),
        "legal": (
            "retaliation adverse action causation",
            "protected activity retaliation caselaw",
        ),
    },
}
EXTERNAL_RESEARCH_DOMAIN_FILTERS_BY_CLAIM = {
    "housing_discrimination": (
        "hud.gov",
        "hudexchange.info",
        "justice.gov",
        "govinfo.gov",
        "law.cornell.edu",
        "lawhelp.org",
        "nhlp.org",
    ),
}
EXTERNAL_RESEARCH_WEB_NOISE_DOMAINS = (
    "merriam-webster.com",
    "cambridge.org",
    "dictionary.com",
    "vocabulary.com",
)
EXTERNAL_RESEARCH_EMPLOYMENT_NOISE_TERMS = (
    "equal employment opportunity commission",
    "employment opportunity commission",
    "workplace retaliation",
    "employer retaliation",
    "employee retaliation",
    "job discrimination",
)
EXTERNAL_RESEARCH_GRIEVANCE_NOISE_TERMS = (
    "sexual misconduct",
    "title ix",
    "student conduct",
    "student grievance",
    "sample grievance",
    "sample grievance appeal",
    "sample letter",
    "apttones",
    "human resources",
    "employee grievance",
    "workplace grievance",
)
TIMELINE_ISSUE_FAMILY_BY_SECTION = {
    "grievance_hearing": "hearing_process",
    "appeal_rights": "response_timeline",
    "adverse_action": "adverse_action",
    "reasonable_accommodation": "response_timeline",
    "selection_criteria": "decision_process",
}
_MONTH_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
_TIMELINE_DATE_PATTERNS = (
    re.compile(r"\b(?P<year>20\d{2}|19\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b"),
    re.compile(rf"\b(?P<month_name>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}}),\s+(?P<year>20\d{{2}}|19\d{{2}})\b", re.IGNORECASE),
    re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>20\d{2}|19\d{2})\b"),
    re.compile(rf"\b(?P<month_name>{_MONTH_PATTERN})\s+(?P<year>20\d{{2}}|19\d{{2}})\b", re.IGNORECASE),
)
_MONTH_NAME_TO_NUMBER = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}
_NON_CASE_TIMELINE_KEYWORDS = (
    "revision date",
    "revision dates",
    "effective date",
    "effective dates",
    "revised",
    "amended",
    "updated",
    "adopted",
    "implementation date",
    "table of contents",
    "federal register",
    "final rule",
    "joint statement",
    "notice pih",
    "hotma",
    "supplementary guidance",
    "administrative plan",
    "adminplan",
)
_CASE_TIMELINE_EVENT_CUES = (
    "written notice",
    "notice of",
    "hearing",
    "appeal",
    "review",
    "request",
    "requested",
    "denied",
    "termination",
    "complaint",
    "response",
    "responded",
    "sent",
    "received",
    "filed",
    "deadline",
    "meeting",
    "interview",
    "grievance",
    "adverse action",
)
_CASE_TIMELINE_ACTION_CUES = (
    "sent",
    "received",
    "denied",
    "requested",
    "filed",
    "responded",
    "scheduled",
    "moved",
    "terminated",
    "complained",
    "emailed",
    "mailed",
)
_CASE_TIMELINE_PARTY_CUES = (
    "tenant",
    "applicant",
    "family",
    "participant",
    "resident",
    "complainant",
    "landlord",
    "voucher",
    "hacc",
)
_CHRONOLOGY_QUERY_TOKENS = {
    "date",
    "dates",
    "timeline",
    "chronology",
    "notice",
    "hearing",
    "review",
    "appeal",
    "response",
    "termination",
    "retaliation",
    "denial",
    "adverse",
}
_CASE_EVIDENCE_PRIORITY_CUES = (
    "written notice",
    "notice of",
    "informal review",
    "grievance hearing",
    "informal hearing",
    "right to appeal",
    "request an informal review",
    "request a grievance hearing",
    "denial of assistance",
    "adverse action",
    "termination",
)
_UPLOAD_CANDIDATE_PROCEDURAL_TERMS = (
    "notice",
    "grievance",
    "hearing",
    "appeal",
    "denial",
    "terminated",
    "termination",
    "adverse action",
)
_UPLOAD_CANDIDATE_NOISE_MARKERS = (
    "<script",
    "window.__feature_flag_state__",
    "previewtext",
    "displayname",
    "hasfullreviewlink",
    "featureflags",
)
_UPLOAD_CANDIDATE_ANALYSIS_TITLE_TERMS = (
    "audit",
    "summary",
    "analysis",
    "report",
    "status",
    "guide",
    "brief",
)
_UPLOAD_CANDIDATE_DOCUMENTATION_PATH_TERMS = (
    "readme",
    "quick_start",
    "quick-reference",
    "quick_reference",
    "documentation_index",
)
_UPLOAD_CANDIDATE_REPOSITORY_SUMMARY_PATH_TERMS = (
    "audit",
    "summary",
    "status",
    "brief",
    "guide",
)
_UPLOAD_CANDIDATE_DOCUMENTATION_MARKERS = (
    "```python",
    "cli reference",
    "key parameters",
    "output_dir",
    "max_turns",
    "run_hacc_adversarial_batch",
)
_EXTERNAL_RESEARCH_LEGAL_FALLBACK_DOMAINS = (
    "ecfr.gov",
    "law.cornell.edu",
    "hud.gov",
    "hudexchange.info",
    "govregs.com",
    "federalregister.gov",
    "justice.gov",
)


def _detect_content_type(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        header = b""
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(path.name)
    return str(guessed or "text/plain")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_legal_citation(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    patterns = (
        r"\b\d+\s+C\.?F\.?R\.?\s+part\s+\d+[\w.()\-]*\s+subpart\s+[A-Z]\b",
        r"\b\d+\s*C\.?F\.?R\.?\s*(?:part\s+)?(?:[\u00a7§]\s*)?[\d\w.()\-]+",
        r"\b\d+\s+U\.?S\.?\s+Code\s*(?:[\u00a7§]\s*)?[\d\w.()\-]+",
        r"\b\d+\s*U\.?S\.?C\.?\s*(?:[\u00a7§]\s*)?[\d\w.()\-]+",
        r"\btitle\s+\d+[^\n]{0,80}?part\s+\d+[\w.()\-]*",
        r"\bpart\s+\d+[\w.()\-]*\s+subpart\s+[A-Z]\b",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return _clean_text(match.group(0))
    return ""


def _canonical_legal_citation_key(value: str) -> str:
    cleaned = _clean_text(value).lower().strip(" .,")
    if not cleaned:
        return ""
    normalized = cleaned.replace("u.s. code", "u.s.c.").replace("§", " § ")
    normalized = re.sub(r"\s+", " ", normalized)
    title_usc_match = re.search(
        r"\btitle\s+(\d+)\s*(?:§\s*)?([\d\w.()\-]+)",
        normalized,
        re.IGNORECASE,
    )
    if title_usc_match:
        return f"usc:{title_usc_match.group(1)}:{title_usc_match.group(2).lower().rstrip('.')}"
    usc_match = re.search(
        r"\b(\d+)\s*u\.?s\.?c\.?\s*(?:§\s*)?([\d\w.()\-]+)",
        normalized,
        re.IGNORECASE,
    )
    if usc_match:
        return f"usc:{usc_match.group(1)}:{usc_match.group(2).lower().rstrip('.')}"
    cfr_match = re.search(
        r"\b(\d+)\s*c\.?f\.?r\.?\s*(?:part\s+)?(?:§\s*)?([\d\w.()\-]+)",
        normalized,
        re.IGNORECASE,
    )
    if cfr_match:
        return f"cfr:{cfr_match.group(1)}:{cfr_match.group(2).lower().rstrip('.')}"
    return ""


def _primary_authority_citation_key(item: Dict[str, Any]) -> str:
    primary_text = " ".join(
        _clean_text(str(part or ""))
        for part in (
            item.get("citation"),
            item.get("title"),
            item.get("url"),
        )
        if _clean_text(str(part or ""))
    )
    return _canonical_legal_citation_key(_extract_legal_citation(primary_text) or primary_text)


def _metadata_query_citation_key(item: Dict[str, Any]) -> str:
    metadata = dict(item.get("metadata") or {})
    details = dict(metadata.get("details") or {})
    query_text = _clean_text(str(details.get("query") or metadata.get("query") or ""))
    if not query_text:
        return ""
    return _canonical_legal_citation_key(_extract_legal_citation(query_text) or query_text)


def _is_mismatched_uscode_releasepoint(item: Dict[str, Any]) -> bool:
    authority_source = _clean_text(str(item.get("authority_source") or item.get("source") or "")).lower()
    url = _clean_text(str(item.get("url") or "")).lower()
    if authority_source != "us_code":
        return False
    if "uscode.house.gov" not in url or "prelimusc" not in url:
        return False
    primary_key = _primary_authority_citation_key(item)
    query_key = _metadata_query_citation_key(item)
    return bool(primary_key and query_key and primary_key != query_key)


def _normalize_guidance_citation(*, title: str, domain: str) -> str:
    cleaned_title = _clean_text(title)
    if not cleaned_title:
        return ""
    normalized = re.sub(r"^PDF", "", cleaned_title, flags=re.IGNORECASE).strip(" -|")
    normalized = re.sub(r"\s*-\s*(HUD(?:\.gov)?|HUD Exchange|HUDExchange(?:\.info)?)$", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*-\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", "", normalized)
    normalized = _clean_text(normalized)
    if not normalized:
        return ""
    if "hud" in domain:
        return f"{normalized} (HUD guidance)"
    if "justice.gov" in domain:
        return f"{normalized} (DOJ guidance)"
    return normalized


def _legal_summary_display_text(item: Dict[str, Any]) -> str:
    citation = _clean_text(str(item.get("citation") or ""))
    title = _clean_text(str(item.get("title") or ""))
    if citation:
        opaque_id = bool(re.fullmatch(r"\d{4}-\d{4,6}", citation))
        if not opaque_id:
            return citation
    return title or citation


def _external_research_prompt_text(item: Dict[str, Any]) -> str:
    return " ".join(
        _clean_text(str(part or ""))
        for part in (
            item.get("citation"),
            item.get("title"),
            item.get("summary"),
            item.get("description"),
            item.get("url"),
            item.get("authority_source"),
            " ".join(
                _clean_text(str(value or ""))
                for value in list(item.get("research_priority_reasons") or [])
                if _clean_text(str(value or ""))
            ),
        )
        if _clean_text(str(part or ""))
    )


def _is_legal_like_web_research_item(item: Dict[str, Any]) -> bool:
    text = _external_research_prompt_text(item).lower()
    url = str(item.get("url") or "").strip().lower()
    legal_like_markers = (
        "law.cornell.edu/uscode",
        "law.cornell.edu/cfr",
        "uscode.house.gov",
        "ecfr.gov",
        "govinfo.gov",
        "federalregister.gov",
        " u.s.c.",
        " u.s. code",
        " c.f.r.",
        " cfr ",
        "§",
    )
    return any(marker in text or marker in url for marker in legal_like_markers)


def _is_relevant_prompt_web_research_item(item: Dict[str, Any]) -> bool:
    text = _external_research_prompt_text(item)
    url = str(item.get("url") or "").strip().lower()
    if _is_non_housing_grievance_noise(text, url=url):
        return False
    if _is_legal_like_web_research_item(item):
        return False
    if ".edu/" in url and not _external_research_has_housing_context(text):
        return False
    return _external_research_has_housing_context(text) and _external_research_has_procedural_context(text)


def _is_relevant_prompt_legal_research_item(item: Dict[str, Any]) -> bool:
    relevance_text = " ".join(
        _clean_text(str(part or ""))
        for part in (
            item.get("citation"),
            item.get("title"),
            item.get("url"),
            item.get("authority_source"),
            " ".join(
                _clean_text(str(value or ""))
                for value in list(item.get("research_priority_reasons") or [])
                if _clean_text(str(value or ""))
            ),
        )
        if _clean_text(str(part or ""))
    )
    citation = str(item.get("citation") or "").strip()
    authority_source = str(item.get("authority_source") or "").strip().lower()
    url = str(item.get("url") or "").strip().lower()
    has_housing = _external_research_has_housing_context(relevance_text)
    has_procedural = _external_research_has_procedural_context(relevance_text)
    has_strong_procedural_fit = _external_research_has_strong_procedural_fit(relevance_text)
    has_grievance_process_fit = _external_research_has_grievance_process_fit(relevance_text)
    if _is_mismatched_uscode_releasepoint(item):
        return False
    if "broad us code releasepoint without grievance-process fit" in relevance_text:
        return False
    if "uscode.house.gov" in url and "prelimusc" in url and not has_grievance_process_fit:
        return False
    if _external_research_has_strong_legal_citation(relevance_text):
        return has_grievance_process_fit or has_strong_procedural_fit
    if _is_opaque_external_research_identifier(citation):
        if "federal_register" in authority_source or "/fr-" in url or "govinfo.gov" in url:
            return has_housing and has_strong_procedural_fit
        return has_housing or has_procedural
    if "federal_register" in authority_source or "/fr-" in url:
        return has_housing and has_strong_procedural_fit
    return has_housing or has_procedural


def _prompt_web_research_display_text(item: Dict[str, Any]) -> str:
    title = _clean_text(str(item.get("title") or item.get("url") or ""))
    url = str(item.get("url") or "").strip()
    if not title:
        return ""
    normalized = _normalize_guidance_citation(title=title, domain=_normalize_domain(url))
    return normalized or title


def _normalize_prompt_legal_display_text(value: str) -> str:
    cleaned = _clean_text(value).strip(" .,-")
    if not cleaned:
        return ""
    cleaned = re.sub(r"--+$", "", cleaned).strip(" .,-")
    cfr_match = re.fullmatch(r"(\d+)\s+C\.?F\.?R\.?\s*(?:§\s*)?([\d.()a-zA-Z-]+)", cleaned, re.IGNORECASE)
    if cfr_match:
        return f"{cfr_match.group(1)} C.F.R. {cfr_match.group(2)}".strip(" .,-")
    usc_match = re.fullmatch(r"(\d+)\s+U\.?S\.?C\.?\s*(?:§\s*)?([\d.()a-zA-Z-]+)", cleaned, re.IGNORECASE)
    if usc_match:
        return f"{usc_match.group(1)} U.S.C. {usc_match.group(2)}".strip(" .,-")
    return cleaned


def _prompt_legal_research_display_text(item: Dict[str, Any]) -> str:
    citation = _clean_text(str(item.get("citation") or ""))
    title = _clean_text(str(item.get("title") or ""))
    url = str(item.get("url") or "").strip()
    domain = _normalize_domain(url)
    extracted_citation = _extract_legal_citation(
        " ".join(
            fragment
            for fragment in (
                citation,
                title,
                url,
                str(item.get("summary") or ""),
                str(item.get("description") or ""),
            )
            if _clean_text(fragment)
        )
    )
    if extracted_citation:
        return _normalize_prompt_legal_display_text(extracted_citation)
    lowered_url = url.lower()
    cfr_title_match = re.search(r"/(?:title-|text/)(\d+)", lowered_url)
    cfr_section_match = re.search(r"/(?:section-|text/\d+/)([\d.()a-z-]+)", lowered_url)
    if cfr_title_match and cfr_section_match and any(candidate in domain for candidate in ("ecfr.gov", "law.cornell.edu")):
        return _normalize_prompt_legal_display_text(f"{cfr_title_match.group(1)} C.F.R. {cfr_section_match.group(1)}")
    cfr_part_match = re.search(r"/part-([\d.()a-z-]+)", lowered_url)
    if cfr_title_match and cfr_part_match and any(candidate in domain for candidate in ("ecfr.gov", "law.cornell.edu")):
        return _normalize_prompt_legal_display_text(f"{cfr_title_match.group(1)} C.F.R. Part {cfr_part_match.group(1)}")
    if any(candidate in domain for candidate in ("hud.gov", "hudexchange.info", "justice.gov")) and title:
        normalized_guidance = _normalize_guidance_citation(title=title, domain=domain)
        if normalized_guidance:
            return normalized_guidance
    return _normalize_prompt_legal_display_text(_legal_summary_display_text(item))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            return str(value)
    return str(value)


def _semantic_token(token: str) -> str:
    normalized = token.lower().strip()
    if not normalized:
        return ""

    canonical_map = {
        "complained": "complain",
        "complaint": "complain",
        "complaints": "complain",
        "engaged": "engage",
        "engaging": "engage",
        "files": "file",
        "filed": "file",
        "filing": "file",
        "policies": "policy",
        "rules": "rule",
    }
    if normalized in canonical_map:
        return canonical_map[normalized]

    for suffix in ("ing", "ed", "es", "s"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
            return normalized[: -len(suffix)]
    return normalized


def _semantic_tokens(value: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    }
    return {
        normalized
        for normalized in (_semantic_token(token) for token in re.findall(r"[a-z0-9]+", value.lower()))
        if normalized and normalized not in stopwords
    }


def _ordered_unique_strings(values: Sequence[str]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(cleaned)
    return ordered


def _sentence_split(text: str) -> List[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    return [_clean_text(part) for part in parts if _clean_text(part)]


def _normalize_domain(value: str) -> str:
    parsed = urlparse(value or "")
    return (parsed.netloc or parsed.path or "").lower()


def _external_research_has_housing_context(text: str) -> bool:
    lowered = str(text or "").lower()
    housing_markers = (
        "housing",
        "hud",
        "tenant",
        "voucher",
        "public housing",
        "lease",
        "rental assistance",
        "housing assistance",
        "project-based rental assistance",
        "section 8",
        "hacc",
        "pha",
        "continuum of care",
        "home investment partnerships",
        "fair housing",
    )
    return any(marker in lowered for marker in housing_markers)


def _external_research_has_procedural_context(text: str) -> bool:
    lowered = str(text or "").lower()
    procedural_markers = (
        "grievance",
        "hearing",
        "informal review",
        "appeal",
        "notice",
        "due process",
        "termination",
        "adverse action",
        "retaliat",
        "accommodation",
        "discrimin",
    )
    return any(marker in lowered for marker in procedural_markers)


def _external_research_has_strong_procedural_fit(text: str) -> bool:
    lowered = str(text or "").lower()
    strong_procedural_markers = (
        "grievance",
        "hearing",
        "informal review",
        "appeal",
        "due process",
        "reasonable accommodation",
        "retaliat",
    )
    return any(marker in lowered for marker in strong_procedural_markers)


def _external_research_has_grievance_process_fit(text: str) -> bool:
    lowered = str(text or "").lower()
    grievance_process_markers = (
        "grievance",
        "informal hearing",
        "hearing",
        "informal review",
        "appeal",
        "notice",
        "due process",
        "termination",
        "adverse action",
        "982.555",
        "part 966",
        "1437d(k)",
    )
    return any(marker in lowered for marker in grievance_process_markers)


def _external_research_has_strong_legal_citation(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "c.f.r.",
            " cfr",
            "u.s.c.",
            " usc",
            "§",
            "part 966",
            "part 982",
            "24 c.f.r.",
            "24 cfr",
            "42 u.s.c.",
            "42 usc",
        )
    )


def _is_opaque_external_research_identifier(value: str) -> bool:
    candidate = str(value or "").strip()
    return bool(candidate) and bool(re.fullmatch(r"\d{4}-\d{4,}", candidate))


def _is_non_housing_grievance_noise(text: str, *, url: str = "") -> bool:
    combined = f"{str(text or '')} {str(url or '')}".lower()
    return any(marker in combined for marker in EXTERNAL_RESEARCH_GRIEVANCE_NOISE_TERMS)


def _safe_json_load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _stable_identifier(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _normalize_timeline_date(match: re.Match[str]) -> tuple[str, str]:
    group_dict = match.groupdict()
    year = str(group_dict.get("year") or "").strip()
    month = str(group_dict.get("month") or "").strip()
    day = str(group_dict.get("day") or "").strip()
    month_name = str(group_dict.get("month_name") or "").strip().lower().rstrip(".")
    if month_name:
        month = _MONTH_NAME_TO_NUMBER.get(month_name, "")
    if year and month and day:
        return (f"{year}-{month.zfill(2)}-{day.zfill(2)}", "day")
    if year and month:
        return (f"{year}-{month.zfill(2)}", "month")
    return (year, "year") if year else ("", "")


def _build_fallback_note(*, requested_mode: str, vector_status: str = "", vector_error: str = "") -> str:
    normalized_requested = _clean_text(requested_mode) or "hybrid"
    normalized_status = _clean_text(vector_status) or "unavailable"
    normalized_error = _clean_text(vector_error)
    note = f"Requested {normalized_requested} search, but vector support is {normalized_status}; using lexical results instead."
    if normalized_error:
        note = f"{note} Vector backend detail: {normalized_error}"
    return note


def _summarize_vector_errors(errors: Sequence[Dict[str, Any]] | None) -> str:
    if not errors:
        return ""

    fragments: List[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        message = _clean_text(item.get("error"))
        if not message:
            continue
        index_name = _clean_text(item.get("index_name"))
        fragments.append(f"{index_name}: {message}" if index_name else message)
    return "; ".join(fragments)


def _summarize_search_payload(payload: Any, *, requested_mode: str, use_vector: bool) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "requested_search_mode": str(requested_mode or "auto"),
            "requested_use_vector": bool(use_vector),
            "effective_search_mode": str(requested_mode or "auto"),
            "status": "unknown",
            "backend_mode": "",
            "vector_status": "",
            "vector_error": "",
            "fallback_note": "",
        }

    effective_mode = str(
        payload.get("effective_search_mode")
        or payload.get("backend_mode")
        or requested_mode
        or "auto"
    )
    return {
        "requested_search_mode": str(requested_mode or "auto"),
        "requested_use_vector": bool(use_vector),
        "effective_search_mode": effective_mode,
        "status": str(payload.get("status") or "unknown"),
        "backend_mode": str(payload.get("backend_mode") or ""),
        "vector_status": str(payload.get("vector_status") or ""),
        "vector_error": str(payload.get("vector_error") or ""),
        "fallback_note": str(payload.get("fallback_note") or ""),
    }


@dataclass
class CorpusDocument:
    document_id: str
    title: str
    text: str
    source_type: str
    source_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    title_tokens: set[str] = field(init=False, repr=False)
    text_tokens: set[str] = field(init=False, repr=False)
    entity_tokens: set[str] = field(init=False, repr=False)
    rule_tokens: set[str] = field(init=False, repr=False)
    title_lower: str = field(init=False, repr=False)
    text_lower: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.title = _clean_text(self.title) or self.document_id
        self.text = str(self.text or "")
        self.source_type = str(self.source_type or "document")
        self.source_path = str(self.source_path or "")
        self.title_lower = self.title.lower()
        self.text_lower = self.text.lower()
        self.title_tokens = _semantic_tokens(self.title)
        self.text_tokens = _semantic_tokens(self.text)
        self.entity_tokens = _semantic_tokens(" ".join(str(entity.get("name") or "") for entity in self.entities))
        self.rule_tokens = _semantic_tokens(" ".join(str(rule.get("text") or "") for rule in self.rules))

    def summary(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "text_length": len(self.text),
            "rule_count": len(self.rules),
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "metadata": dict(self.metadata),
        }


class HACCResearchEngine:
    def __init__(
        self,
        *,
        repo_root: Optional[Path | str] = None,
        parsed_dir: Optional[Path | str] = None,
        parse_manifest_path: Optional[Path | str] = None,
        knowledge_graph_dir: Optional[Path | str] = None,
    ) -> None:
        self.repo_root = Path(repo_root or REPO_ROOT).resolve()
        self.parsed_dir = Path(parsed_dir or (self.repo_root / "research_results/documents/parsed")).resolve()
        self.parse_manifest_path = Path(
            parse_manifest_path or (self.repo_root / "research_results/documents/parse_manifest.json")
        ).resolve()
        self.knowledge_graph_dir = Path(
            knowledge_graph_dir or (self.repo_root / "hacc_website/knowledge_graph")
        ).resolve()
        self.repository_ingest_dir = (self.repo_root / "research_results/documents/repository_ingest").resolve()
        self.default_embedding_dir = (self.knowledge_graph_dir / "embeddings").resolve()
        self.default_index_dir = (self.repo_root / "research_results/search_indexes").resolve()
        self.default_index_path = self.default_index_dir / "hacc_corpus.summary.json"
        self._documents: Optional[List[CorpusDocument]] = None

    def _retrieval_orchestrator(self) -> Any:
        if RetrievalOrchestrator is None:
            return None
        try:
            return RetrievalOrchestrator()
        except Exception:
            return None

    def _build_retrieval_query_context(self, query_text: str, *, claim_type: str = "") -> Dict[str, Any]:
        orchestrator = self._retrieval_orchestrator()
        if orchestrator is None:
            return {}
        try:
            return dict(
                orchestrator.build_query_context(
                    query=query_text,
                    claim_type=claim_type or "",
                    complaint_type=claim_type or "",
                    jurisdiction="federal",
                    max_queries=4,
                )
                or {}
            )
        except Exception:
            return {}

    def _external_research_query_plan(self, query_text: str, *, claim_type: str = "") -> Dict[str, Any]:
        normalized_query = _clean_text(query_text)
        normalized_claim_type = str(claim_type or "").strip().lower()
        query_context = _json_safe(
            self._build_retrieval_query_context(normalized_query, claim_type=normalized_claim_type)
        )
        query_variants = [
            str(item).strip()
            for item in list(query_context.get("queries") or [])
            if str(item).strip()
        ]
        claim_label = normalized_claim_type.replace("_", " ").strip()
        hints = dict(EXTERNAL_RESEARCH_HINTS_BY_CLAIM.get(normalized_claim_type) or {})

        def _dedupe_queries(values: Sequence[str]) -> List[str]:
            ordered: List[str] = []
            seen: set[str] = set()
            for value in values:
                cleaned = str(value or "").strip()
                if not cleaned:
                    continue
                lowered = cleaned.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                ordered.append(cleaned)
            return ordered

        web_queries = _dedupe_queries(
            [
                normalized_query,
                *[str(hint).strip() for hint in list(hints.get("web") or []) if str(hint).strip()],
                f"{claim_label} {normalized_query}" if claim_label else "",
                *query_variants,
                *[
                    f"{normalized_query} {hint}" if normalized_query else hint
                    for hint in list(hints.get("web") or [])
                ],
            ]
        )
        legal_queries = _dedupe_queries(
            [
                normalized_query,
                *[str(hint).strip() for hint in list(hints.get("legal") or []) if str(hint).strip()],
                f"{claim_label} {normalized_query}" if claim_label else "",
                *query_variants,
                *[
                    f"{normalized_query} {hint}" if normalized_query else hint
                    for hint in list(hints.get("legal") or [])
                ],
            ]
        )
        return {
            "query_context": query_context,
            "web_queries": web_queries,
            "legal_queries": legal_queries,
        }

    def _preferred_external_web_domains(self, claim_type: str) -> List[str]:
        normalized_claim_type = str(claim_type or "").strip().lower()
        return [
            str(item).strip().lower()
            for item in list(EXTERNAL_RESEARCH_DOMAIN_FILTERS_BY_CLAIM.get(normalized_claim_type) or [])
            if str(item).strip()
        ]

    def _default_claim_type_for_query(self, query_text: str) -> str:
        lowered_query = _clean_text(query_text).lower()
        if any(token in lowered_query for token in ("housing", "tenant", "voucher", "hud", "public housing")):
            return "housing_discrimination"
        return ""

    def _legal_authority_query_variants(self, query_text: str) -> List[str]:
        cleaned_query = _clean_text(query_text)
        if not cleaned_query:
            return []

        variants: List[str] = [cleaned_query]
        citation = _extract_legal_citation(cleaned_query)
        if citation and citation.lower() != cleaned_query.lower():
            variants.append(citation)

        lowered_query = cleaned_query.lower()
        has_housing_context = any(token in lowered_query for token in ("housing", "tenant", "voucher", "participant", "hud"))
        has_procedure_context = any(token in lowered_query for token in ("grievance", "hearing", "appeal", "notice", "informal review"))
        has_retaliation_context = "retaliation" in lowered_query

        if has_housing_context and has_procedure_context:
            variants.extend(
                [
                    "24 C.F.R. 982.555 informal hearing",
                    "24 C.F.R. part 966 grievance procedures",
                    "42 U.S.C. 1437d grievance procedure",
                ]
            )
        if has_housing_context and has_retaliation_context:
            variants.extend(
                [
                    "Fair Housing Act retaliation",
                    "42 U.S.C. 3604 fair housing retaliation",
                ]
            )

        ordered: List[str] = []
        seen: set[str] = set()
        for value in variants:
            normalized = _clean_text(value)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
        return ordered[:5]

    def _aggregate_external_discovery_results(
        self,
        payloads: Sequence[Dict[str, Any]],
        *,
        result_key: str,
        dedupe_keys: Sequence[str],
        max_results: int,
    ) -> Dict[str, Any]:
        aggregated_results: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            attempts.append(
                {
                    "query": str(payload.get("query") or "").strip(),
                    "status": str(payload.get("status") or ""),
                    "result_count": int(payload.get("result_count", len(list(payload.get(result_key) or []))) or 0),
                    "error": str(payload.get("error") or "").strip(),
                }
            )
            for item in list(payload.get(result_key) or []):
                if not isinstance(item, dict):
                    continue
                dedupe_value = ""
                for key in dedupe_keys:
                    candidate = str(item.get(key) or "").strip().lower()
                    if candidate:
                        dedupe_value = f"{key}:{candidate}"
                        break
                if not dedupe_value or dedupe_value in seen:
                    continue
                seen.add(dedupe_value)
                aggregated_results.append(dict(item))
                if len(aggregated_results) >= max_results:
                    break
            if len(aggregated_results) >= max_results:
                break

        integration_status = {}
        for payload in payloads:
            if isinstance(payload, dict) and isinstance(payload.get("integration_status"), dict):
                integration_status = dict(payload.get("integration_status") or {})
                break

        status = "success" if aggregated_results else "error" if any(attempt.get("error") for attempt in attempts) else "success"
        return {
            "status": status,
            "result_count": len(aggregated_results),
            "results": aggregated_results[:max_results],
            "attempts": attempts,
            "integration_status": integration_status,
        }

    def _promote_web_results_to_legal_authorities(
        self,
        web_payload: Dict[str, Any],
        *,
        max_results: int,
        authority_source: str = "web_fallback",
    ) -> Dict[str, Any]:
        promoted_results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in list(web_payload.get("results") or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            domain = _normalize_domain(url)
            if not domain or not any(candidate in domain for candidate in _EXTERNAL_RESEARCH_LEGAL_FALLBACK_DOMAINS):
                continue
            key = url.lower() or str(item.get("title") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            title = _clean_text(str(item.get("title") or url))
            citation = _extract_legal_citation(
                " ".join(
                    fragment
                    for fragment in (
                        title,
                        url,
                        str(item.get("description") or ""),
                        str(item.get("summary") or ""),
                    )
                    if _clean_text(fragment)
                )
            )
            if not citation and domain.endswith("law.cornell.edu"):
                citation = title
            if not citation and domain.endswith("ecfr.gov"):
                citation = title
            if not citation and any(candidate in domain for candidate in ("hud.gov", "hudexchange.info", "justice.gov")):
                citation = _normalize_guidance_citation(title=title, domain=domain)
            promoted_results.append(
                {
                    "title": title,
                    "citation": citation,
                    "url": url,
                    "summary": str(item.get("description") or item.get("content") or item.get("summary") or "").strip(),
                    "authority_source": authority_source,
                    "source_domain": domain,
                    "promoted_from": "web_discovery",
                }
            )
            if len(promoted_results) >= max_results:
                break
        return {
            "status": "success" if promoted_results else "success",
            "result_count": len(promoted_results),
            "results": promoted_results,
            "attempts": [
                {
                    "query": "",
                    "status": "success" if promoted_results else "success",
                    "result_count": len(promoted_results),
                    "error": "",
                    "fallback": authority_source,
                }
            ],
            "integration_status": dict(web_payload.get("integration_status") or {}),
        }

    def _discover_legal_authorities_via_web_search(
        self,
        query_variants: Sequence[str],
        *,
        max_results: int,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        seen: set[str] = set()
        integration_status: Dict[str, Any] = {}
        for candidate_query in query_variants:
            web_payload = self.discover(
                candidate_query,
                max_results=max_results,
                domain_filter=_EXTERNAL_RESEARCH_LEGAL_FALLBACK_DOMAINS,
                scrape=False,
            )
            if isinstance(web_payload.get("integration_status"), dict) and not integration_status:
                integration_status = dict(web_payload.get("integration_status") or {})
            promoted_payload = self._promote_web_results_to_legal_authorities(
                web_payload,
                max_results=max_results,
                authority_source="web_legal_search",
            )
            added = 0
            for item in list(promoted_payload.get("results") or []):
                if not isinstance(item, dict):
                    continue
                dedupe_key = str(item.get("citation") or item.get("title") or item.get("url") or "").strip().lower()
                if not dedupe_key or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                results.append(dict(item))
                added += 1
                if len(results) >= max_results:
                    break
            attempts.append(
                {
                    "source": "web_legal_search",
                    "query": candidate_query,
                    "result_count": added,
                    "error": "",
                }
            )
            if len(results) >= max_results:
                break
        return {
            "status": "success" if results else "success",
            "result_count": len(results[:max_results]),
            "results": results[:max_results],
            "attempts": attempts,
            "integration_status": integration_status,
        }

    def _normalized_retrieval_source_type(self, source_type: str) -> str:
        normalized = str(source_type or "").strip().lower()
        if normalized in {"repository_evidence", "parsed_document"}:
            return "evidence"
        if normalized in {"knowledge_graph"}:
            return "legal_corpus"
        return normalized or "evidence"

    def _build_normalized_retrieval_record(
        self,
        item: Dict[str, Any],
        *,
        query_text: str,
        claim_type: str = "",
    ) -> Any:
        if NormalizedRetrievalRecord is None:
            return None
        metadata = dict(item.get("metadata") or {})
        metadata.setdefault("document_id", str(item.get("document_id") or ""))
        metadata.setdefault("source_path", str(item.get("source_path") or ""))
        metadata.setdefault("relative_path", str(metadata.get("relative_path") or ""))
        metadata.setdefault("title", str(item.get("title") or ""))
        metadata.setdefault("complaint_type", str(claim_type or ""))
        metadata.setdefault("chronology_summary", dict(item.get("chronology_summary") or {}))
        metadata.setdefault("matched_rules", list(item.get("matched_rules") or []))
        metadata.setdefault("matched_entities", list(item.get("matched_entities") or []))
        return NormalizedRetrievalRecord(
            source_type=self._normalized_retrieval_source_type(str(item.get("source_type") or "")),
            source_name=str(item.get("source_type") or "hacc_corpus"),
            query=query_text,
            title=str(item.get("title") or ""),
            url=str(item.get("source_path") or ""),
            citation=str(metadata.get("relative_path") or item.get("source_path") or item.get("title") or ""),
            snippet=str(item.get("snippet") or ""),
            content=str(item.get("snippet") or ""),
            score=float(item.get("score", 0.0) or 0.0),
            confidence=min(1.0, max(0.0, float(item.get("score", 0.0) or 0.0) / 25.0)),
            metadata=metadata,
        )

    def _rerank_result_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        query_text: str,
        claim_type: str = "",
        max_results: int,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        orchestrator = self._retrieval_orchestrator()
        query_context = self._build_retrieval_query_context(query_text, claim_type=claim_type)
        if orchestrator is None or NormalizedRetrievalRecord is None:
            return list(items)[:max_results], {}, {}

        records = []
        record_map: Dict[str, Dict[str, Any]] = {}
        for index, item in enumerate(items):
            record = self._build_normalized_retrieval_record(
                item,
                query_text=query_text,
                claim_type=claim_type,
            )
            if record is None:
                continue
            key = record.dedupe_key() or f"anonymous:{index}"
            records.append(record)
            record_map[key] = dict(item)

        if not records:
            return list(items)[:max_results], query_context, {}

        try:
            ranked_records = orchestrator.merge_and_rank(records, max_results=max_results, query_context=query_context)
            support_bundle = dict(orchestrator.build_support_bundle(ranked_records, max_items_per_bucket=5) or {})
        except Exception:
            return list(items)[:max_results], query_context, {}

        reranked: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        for fallback_index, record in enumerate(ranked_records):
            key = record.dedupe_key() or f"anonymous:{fallback_index}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            item = dict(record_map.get(key) or {})
            if not item:
                continue
            item["score"] = round(float((record.metadata or {}).get("orchestrator_composite_score", record.score) or record.score), 6)
            item["metadata"] = dict(record.metadata or {})
            reranked.append(item)

        if not reranked:
            return list(items)[:max_results], query_context, support_bundle
        return reranked[:max_results], query_context, support_bundle

    def load_corpus(self, *, force_reload: bool = False) -> List[CorpusDocument]:
        if self._documents is not None and not force_reload:
            return list(self._documents)

        documents = []
        documents.extend(self._load_parsed_documents())
        documents.extend(self._load_repository_evidence_documents())
        documents.extend(self._load_knowledge_graph_documents())
        self._documents = documents
        return list(documents)

    def corpus_records(self) -> List[Dict[str, Any]]:
        return [self._serialize_document(document) for document in self.load_corpus()]

    def integration_status(self) -> Dict[str, Any]:
        return self._integration_status()

    def build_index(self, output_path: Optional[Path | str] = None) -> Dict[str, Any]:
        documents = self.load_corpus()
        records_output_path = None
        manifest_output_path = None
        output = None
        if output_path:
            output = Path(output_path).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            records_output_path = output.with_suffix(".records.jsonl")
            manifest_output_path = output.with_suffix(".manifest.json")
            with records_output_path.open("w", encoding="utf-8") as handle:
                for record in self.corpus_records():
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        payload = {
            "status": "success",
            "document_count": len(documents),
            "source_counts": self._source_counts(documents),
            "knowledge_graph_dir": str(self.knowledge_graph_dir),
            "parsed_dir": str(self.parsed_dir),
            "documents": [document.summary() for document in documents],
            "integration_status": self._integration_status(),
        }
        if output_path:
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            payload["output_path"] = str(output)
            payload["records_path"] = str(records_output_path)
            if manifest_output_path is not None:
                manifest = {
                    "index_name": output.stem,
                    "summary_path": str(output),
                    "records_path": str(records_output_path),
                    "document_count": len(documents),
                    "source_counts": self._source_counts(documents),
                }
                manifest_output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
                payload["manifest_path"] = str(manifest_output_path)
        return payload

    def build_vector_index(
        self,
        *,
        output_dir: Optional[Path | str] = None,
        index_name: str = "hacc_corpus",
        batch_size: int = 32,
    ) -> Dict[str, Any]:
        if create_vector_index is None:
            return {
                "status": "unavailable",
                "index_name": index_name,
                "error": INTEGRATION_IMPORT_ERROR or "vector index adapter unavailable",
                "integration_status": self._integration_status(),
            }

        output_path = Path(output_dir or self.default_index_dir).resolve()
        records = self._build_vector_documents(self.load_corpus())
        payload = create_vector_index(
            records,
            index_name=index_name,
            output_dir=str(output_path),
            batch_size=batch_size,
        )
        if isinstance(payload, dict):
            payload["integration_status"] = self._integration_status()
        return payload

    def ensure_vector_index(
        self,
        *,
        index_name: str = "hacc_corpus",
        index_dir: Optional[Path | str] = None,
        batch_size: int = 32,
    ) -> Dict[str, Any]:
        candidate_indexes = self._resolve_vector_indexes(index_name=index_name, index_dir=index_dir)
        for candidate in candidate_indexes:
            manifest_path = Path(candidate["index_dir"]) / f"{candidate['index_name']}.manifest.json"
            if manifest_path.exists():
                return {
                    "status": "existing",
                    "index_name": candidate["index_name"],
                    "index_dir": candidate["index_dir"],
                    "manifest_path": str(manifest_path),
                    "integration_status": self._integration_status(),
                }

        if create_vector_index is None or not VECTOR_STORE_AVAILABLE or not EMBEDDINGS_AVAILABLE:
            return {
                "status": "unavailable",
                "index_name": index_name,
                "index_dir": str(Path(index_dir or self.default_index_dir).resolve()),
                "error": INTEGRATION_IMPORT_ERROR or VECTOR_STORE_ERROR or "vector index adapter unavailable",
                "integration_status": self._integration_status(),
            }

        return self.build_vector_index(
            output_dir=index_dir or self.default_index_dir,
            index_name=index_name,
            batch_size=batch_size,
        )

    def search_package(
        self,
        query: str,
        *,
        top_k: int = 10,
        vector_top_k: Optional[int] = None,
        index_name: str = "hacc_corpus",
        index_dir: Optional[Path | str] = None,
        source_types: Optional[Sequence[str]] = None,
        auto_build_index: bool = True,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        index_status: Optional[Dict[str, Any]] = None
        vector_ready = self._has_preferred_vector_index(index_name=index_name, index_dir=index_dir)

        if auto_build_index and not vector_ready:
            index_status = self.ensure_vector_index(index_name=index_name, index_dir=index_dir)
            vector_ready = self._has_preferred_vector_index(index_name=index_name, index_dir=index_dir)

        if vector_ready:
            payload = self.hybrid_search(
                query_text,
                top_k=top_k,
                vector_top_k=vector_top_k,
                index_name=index_name,
                index_dir=index_dir,
                source_types=source_types,
            )
            payload["backend_mode"] = "shared_hybrid"
            effective_mode = str(payload.get("effective_search_mode") or "")
            if effective_mode == "hybrid" and str(payload.get("vector_status") or "") == "success":
                payload["effective_search_mode"] = "shared_hybrid"
                payload["fallback_note"] = ""
            else:
                payload.setdefault("effective_search_mode", "shared_hybrid")
            if str(payload.get("effective_search_mode") or "") != "shared_hybrid":
                payload["fallback_note"] = _build_fallback_note(
                    requested_mode="package/shared hybrid",
                    vector_status=str(payload.get("vector_status") or "unavailable"),
                    vector_error=str(payload.get("vector_error") or ""),
                )
        else:
            payload = self.search_local(query_text, top_k=top_k, source_types=source_types)
            payload["backend_mode"] = "lexical_fallback"
            payload["effective_search_mode"] = "lexical_fallback"
            payload["vector_status"] = "unavailable"
            if index_status and index_status.get("status") == "unavailable":
                payload["vector_error"] = index_status.get("error")
            payload["fallback_note"] = _build_fallback_note(
                requested_mode="package/shared hybrid",
                vector_status=str(payload.get("vector_status") or "unavailable"),
                vector_error=str(payload.get("vector_error") or ""),
            )

        payload["index_status"] = index_status or {
            "status": "existing" if vector_ready else "skipped",
            "index_name": index_name,
            "index_dir": str(Path(index_dir or self.default_index_dir).resolve()),
        }
        payload["integration_status"] = self._integration_status()
        return payload

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        use_vector: bool = False,
        search_mode: str = "package",
        vector_top_k: Optional[int] = None,
        index_name: str = "hacc_corpus",
        index_dir: Optional[Path | str] = None,
        source_types: Optional[Sequence[str]] = None,
        min_score: float = 0.0,
    ) -> Dict[str, Any]:
        normalized_mode = str(search_mode or "auto").strip().lower()
        if normalized_mode not in {"auto", "lexical", "hybrid", "vector", "package"}:
            normalized_mode = "auto"

        should_use_vector = bool(use_vector)
        if normalized_mode == "package":
            return self.search_package(
                query,
                top_k=top_k,
                vector_top_k=vector_top_k,
                index_name=index_name,
                index_dir=index_dir,
                source_types=source_types,
                auto_build_index=True,
            )
        if normalized_mode == "vector":
            return self.search_vector(
                query,
                index_name=index_name,
                index_dir=index_dir,
                top_k=vector_top_k or top_k,
            )
        if normalized_mode == "hybrid":
            should_use_vector = True
        elif normalized_mode == "auto":
            should_use_vector = bool(use_vector) or self._has_preferred_vector_index(
                index_name=index_name,
                index_dir=index_dir,
            )

        if should_use_vector:
            return self.hybrid_search(
                query,
                top_k=top_k,
                vector_top_k=vector_top_k,
                index_name=index_name,
                index_dir=index_dir,
                source_types=source_types,
            )
        return self.search_local(
            query,
            top_k=top_k,
            source_types=source_types,
            min_score=min_score,
        )

    def search_vector(
        self,
        query: str,
        *,
        index_name: str = "hacc_corpus",
        index_dir: Optional[Path | str] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        if search_vector_index is None:
            return {
                "status": "unavailable",
                "query": _clean_text(query),
                "results": [],
                "error": INTEGRATION_IMPORT_ERROR or "vector search adapter unavailable",
                "integration_status": self._integration_status(),
            }

        query_text = _clean_text(query)
        candidate_indexes = self._resolve_vector_indexes(index_name=index_name, index_dir=index_dir)
        aggregated_results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        statuses: List[str] = []

        for candidate in candidate_indexes:
            payload = search_vector_index(
                query_text,
                index_name=candidate["index_name"],
                index_dir=candidate["index_dir"],
                top_k=top_k,
            )
            if not isinstance(payload, dict):
                errors.append(
                    {
                        "index_name": candidate["index_name"],
                        "index_dir": candidate["index_dir"],
                        "error": "Unexpected vector search response",
                    }
                )
                statuses.append("error")
                continue

            statuses.append(str(payload.get("status") or "unknown"))
            if payload.get("status") != "success":
                errors.append(
                    {
                        "index_name": candidate["index_name"],
                        "index_dir": candidate["index_dir"],
                        "error": payload.get("error", ""),
                    }
                )
                continue

            for item in list(payload.get("results", []) or []):
                enriched = dict(item)
                metadata = enriched.get("metadata") if isinstance(enriched.get("metadata"), dict) else {}
                metadata = dict(metadata)
                metadata.setdefault("vector_index_name", candidate["index_name"])
                metadata.setdefault("vector_index_dir", candidate["index_dir"])
                enriched["metadata"] = metadata
                enriched["vector_index_name"] = candidate["index_name"]
                enriched["vector_index_dir"] = candidate["index_dir"]
                aggregated_results.append(enriched)

        aggregated_results.sort(
            key=lambda item: (
                -float(item.get("score", 0.0) or 0.0),
                str(item.get("vector_index_name") or ""),
                str(item.get("id") or ""),
            )
        )

        status = "success" if aggregated_results else "unavailable" if all(value == "unavailable" for value in statuses) else "error" if errors else "success"
        error_summary = _summarize_vector_errors(errors)
        return {
            "status": status,
            "query": query_text,
            "results": aggregated_results[:top_k],
            "searched_indexes": candidate_indexes,
            "errors": errors,
            "error": error_summary,
            "integration_status": self._integration_status(),
        }

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        vector_top_k: Optional[int] = None,
        index_name: str = "hacc_corpus",
        index_dir: Optional[Path | str] = None,
        source_types: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        lexical = self.search(
            query,
            top_k=max(top_k, vector_top_k or top_k),
            search_mode="lexical",
            source_types=source_types,
        )
        vector = self.search_vector(
            query,
            index_name=index_name,
            index_dir=index_dir,
            top_k=vector_top_k or top_k,
        )

        lexical_results = list(lexical.get("results", []) or [])
        vector_results = list(vector.get("results", []) or [])
        merged: Dict[str, Dict[str, Any]] = {}

        for item in lexical_results:
            doc_id = str(item.get("document_id") or "")
            if not doc_id:
                continue
            merged[doc_id] = {
                **item,
                "document_id": doc_id,
                "lexical_score": float(item.get("score", 0.0) or 0.0),
                "vector_score": 0.0,
                "score": float(item.get("score", 0.0) or 0.0),
                "search_modes": ["lexical"],
            }

        for item in vector_results:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            doc_id = str(metadata.get("document_id") or item.get("id") or "")
            if not doc_id:
                continue
            vector_score = float(item.get("score", 0.0) or 0.0)
            if doc_id in merged:
                merged_item = merged[doc_id]
                merged_item["vector_score"] = max(float(merged_item.get("vector_score", 0.0) or 0.0), vector_score)
                merged_item["score"] = float(merged_item.get("lexical_score", 0.0) or 0.0) + (vector_score * 25.0)
                if "vector" not in merged_item["search_modes"]:
                    merged_item["search_modes"].append("vector")
            else:
                merged[doc_id] = {
                    "document_id": doc_id,
                    "title": str(metadata.get("title") or metadata.get("source_file") or doc_id),
                    "source_type": str(metadata.get("source_type") or "vector_document"),
                    "source_path": str(metadata.get("source_path") or ""),
                    "snippet": str(item.get("text") or "")[:500],
                    "matched_rules": [],
                    "matched_entities": [],
                    "metadata": metadata,
                    "lexical_score": 0.0,
                    "vector_score": vector_score,
                    "score": vector_score * 25.0,
                    "search_modes": ["vector"],
                }

        ranked = sorted(merged.values(), key=lambda item: (-float(item.get("score", 0.0)), item.get("title", "")))
        reranked, query_context, support_bundle = self._rerank_result_items(
            ranked,
            query_text=_clean_text(query),
            max_results=top_k,
        )
        payload = {
            "status": "success",
            "query": _clean_text(query),
            "results": reranked,
            "returned_result_count": min(top_k, len(reranked)),
            "lexical_status": lexical.get("status"),
            "vector_status": vector.get("status"),
            "vector_error": vector.get("error"),
            "query_context": query_context,
            "support_bundle": support_bundle,
            "reranked_by_orchestrator": bool(support_bundle),
            "integration_status": self._integration_status(),
        }
        if vector.get("status") == "success":
            payload["effective_search_mode"] = "hybrid"
        else:
            payload["effective_search_mode"] = "lexical_only"
            payload["fallback_note"] = _build_fallback_note(
                requested_mode="hybrid",
                vector_status=str(vector.get("status") or "unavailable"),
                vector_error=str(vector.get("error") or ""),
            )
        return payload

    def search_local(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_types: Optional[Sequence[str]] = None,
        min_score: float = 0.0,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        query_tokens = _semantic_tokens(query_text)
        documents = self.load_corpus()
        allowed_types = {value.lower() for value in source_types or []}

        ranked_results = []
        for document in documents:
            if allowed_types and document.source_type.lower() not in allowed_types:
                continue
            score, matched_rules, matched_entities = self._score_document(
                query_text=query_text,
                query_tokens=query_tokens,
                document=document,
            )
            if score < min_score:
                continue
            ranked_results.append(
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "score": round(score, 4),
                    "source_type": document.source_type,
                    "source_path": document.source_path,
                    "snippet": self._extract_snippet(query_text, query_tokens, document, matched_rules),
                    "matched_rules": matched_rules[:3],
                    "matched_entities": matched_entities[:5],
                    "metadata": dict(document.metadata),
                    "chronology_summary": dict(document.metadata.get("chronology_summary") or {}),
                }
            )

        ranked_results.sort(key=lambda item: (-float(item["score"]), item["title"]))
        chronology_ready_result_count = sum(
            1
            for item in ranked_results
            if isinstance(item.get("chronology_summary"), dict)
            and int((item.get("chronology_summary") or {}).get("timeline_anchor_count", 0) or 0) > 0
        )
        anchor_section_counts: Dict[str, int] = {}
        for item in ranked_results[:top_k]:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            for label in list(metadata.get("anchor_sections") or []):
                label_text = str(label or "").strip()
                if label_text:
                    anchor_section_counts[label_text] = int(anchor_section_counts.get(label_text, 0) or 0) + 1
        reranked_results, query_context, support_bundle = self._rerank_result_items(
            ranked_results,
            query_text=query_text,
            max_results=top_k,
        )
        chronology_ready_result_count = sum(
            1
            for item in reranked_results
            if isinstance(item.get("chronology_summary"), dict)
            and int((item.get("chronology_summary") or {}).get("timeline_anchor_count", 0) or 0) > 0
        )
        anchor_section_counts = {}
        for item in reranked_results[:top_k]:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            for label in list(metadata.get("anchor_sections") or []):
                label_text = str(label or "").strip()
                if label_text:
                    anchor_section_counts[label_text] = int(anchor_section_counts.get(label_text, 0) or 0) + 1
        return {
            "status": "success",
            "query": query_text,
            "document_count": len(documents),
            "returned_result_count": min(top_k, len(reranked_results)),
            "chronology_ready_result_count": chronology_ready_result_count,
            "anchor_section_counts": anchor_section_counts,
            "results": reranked_results[:top_k],
            "query_context": query_context,
            "support_bundle": support_bundle,
            "reranked_by_orchestrator": bool(support_bundle),
            "integration_status": self._integration_status(),
        }

    def discover(
        self,
        query: str,
        *,
        max_results: int = 10,
        engines: Optional[List[str]] = None,
        domain_filter: Optional[Sequence[str] | str] = None,
        scrape: bool = False,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        if search_multi_engine_web is None and search_brave_web is None:
            return {
                "status": "unavailable",
                "query": query_text,
                "results": [],
                "error": INTEGRATION_IMPORT_ERROR or "ipfs_datasets search adapter unavailable",
                "integration_status": self._integration_status(),
            }

        if search_multi_engine_web is not None:
            results = search_multi_engine_web(query_text, max_results=max_results, engines=engines)
        else:
            results = search_brave_web(query_text, max_results=max_results)

        normalized_filters = self._normalize_domain_filters(domain_filter)
        if normalized_filters:
            results = [item for item in results if self._matches_domain_filter(item, normalized_filters)]

        if scrape and scrape_web_content is not None:
            for item in results[: min(len(results), 5)]:
                scraped = scrape_web_content(str(item.get("url") or ""))
                item["scrape"] = {
                    "success": bool(scraped.get("success", False)),
                    "errors": list(scraped.get("errors", []) or []),
                    "content_preview": str(scraped.get("content", "") or "")[:500],
                }

        return {
            "status": "success",
            "query": query_text,
            "engines": list(engines or []),
            "domain_filter": sorted(normalized_filters),
            "scrape_enabled": bool(scrape),
            "result_count": len(results),
            "results": results[:max_results],
            "integration_status": self._integration_status(),
        }

    def discover_seeded_commoncrawl(
        self,
        queries: Sequence[str] | str | Path,
        *,
        cc_limit: int = 1000,
        top_per_site: int = 50,
        fetch_top: int = 0,
        sleep_seconds: float = 0.5,
    ) -> Dict[str, Any]:
        if discover_seeded_commoncrawl is None:
            return {
                "status": "unavailable",
                "queries": list(queries) if isinstance(queries, (list, tuple)) else [str(queries)],
                "error": INTEGRATION_IMPORT_ERROR or "seeded commoncrawl adapter unavailable",
                "integration_status": self._integration_status(),
            }

        query_path: Optional[Path] = None
        cleanup_path: Optional[Path] = None
        if isinstance(queries, (str, Path)) and Path(queries).exists():
            query_path = Path(queries)
        else:
            if isinstance(queries, (str, Path)):
                query_lines = [str(queries)]
            else:
                query_lines = [str(item).strip() for item in queries if str(item).strip()]
            handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
            with handle:
                handle.write("\n".join(query_lines) + "\n")
            cleanup_path = Path(handle.name)
            query_path = cleanup_path

        try:
            payload = discover_seeded_commoncrawl(
                query_path,
                cc_limit=cc_limit,
                top_per_site=top_per_site,
                fetch_top=fetch_top,
                sleep_seconds=sleep_seconds,
            )
        finally:
            if cleanup_path is not None and cleanup_path.exists():
                cleanup_path.unlink(missing_ok=True)

        if isinstance(payload, dict):
            payload.setdefault("integration_status", self._integration_status())
        return payload

    def discover_legal_authorities(
        self,
        query: str,
        *,
        max_results: int = 10,
        claim_type: str = "",
        title: Optional[str] = None,
        court: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        if not query_text:
            return {
                "status": "error",
                "query": query_text,
                "results": [],
                "error": "empty query",
                "integration_status": self._integration_status(),
            }

        if not LEGAL_SCRAPERS_AVAILABLE:
            return {
                "status": "unavailable",
                "query": query_text,
                "results": [],
                "error": LEGAL_SCRAPERS_ERROR or INTEGRATION_IMPORT_ERROR or "legal scraper adapter unavailable",
                "integration_status": self._integration_status(),
            }

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        attempts: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        collected_result_limit = max(max_results * 4, max_results)
        query_variants = self._legal_authority_query_variants(query_text) or [query_text]
        operations = [
            ("us_code", search_us_code, {"title": title, "max_results": max_results}),
            (
                "federal_register",
                search_federal_register,
                {"start_date": start_date, "end_date": end_date, "max_results": max_results},
            ),
            ("recap", search_recap_documents, {"court": court, "max_results": max_results}),
        ]

        for candidate_query in query_variants:
            before_count = len(results)
            for source_name, func, kwargs in operations:
                if func is None:
                    continue
                try:
                    source_results = func(candidate_query, **kwargs)
                except Exception as exc:  # pragma: no cover - exercised through degraded integrations
                    errors.append({"source": source_name, "query": candidate_query, "error": str(exc)})
                    attempts.append({"source": source_name, "query": candidate_query, "result_count": 0, "error": str(exc)})
                    continue
                added = 0
                for item in list(source_results or []):
                    citation = str(item.get("citation") or item.get("title") or item.get("url") or "").strip()
                    dedupe_key = f"{source_name}:{citation.lower()}"
                    if not citation or dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    results.append(
                        {
                            **item,
                            "authority_source": source_name,
                            "title": str(item.get("title") or citation),
                            "citation": citation,
                            "url": str(item.get("url") or ""),
                            "score": float(item.get("relevance_score", 0.5) or 0.5),
                        }
                    )
                    added += 1
                    if len(results) >= collected_result_limit:
                        break
                attempts.append({"source": source_name, "query": candidate_query, "result_count": added, "error": ""})
                if len(results) >= collected_result_limit:
                    break
            if len(results) >= collected_result_limit and len(results) > before_count:
                break

        if not results:
            web_fallback_payload = self._discover_legal_authorities_via_web_search(
                query_variants,
                max_results=max_results,
            )
            for item in list(web_fallback_payload.get("results") or []):
                if not isinstance(item, dict):
                    continue
                citation = str(item.get("citation") or item.get("title") or item.get("url") or "").strip()
                dedupe_key = f"web_legal_search:{citation.lower()}"
                if not citation or dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                results.append(dict(item))
            attempts.extend(list(web_fallback_payload.get("attempts") or []))

        ranking_claim_type = str(claim_type or "").strip().lower() or self._default_claim_type_for_query(query_text)
        ranked_payload = self._rank_external_research_payload(
            {
                "status": "success" if results else "error" if errors else "success",
                "result_count": len(results),
                "results": results,
                "errors": errors,
                "attempts": attempts,
                "integration_status": self._integration_status(),
            },
            query_text=query_text,
            claim_type=ranking_claim_type,
            result_kind="legal",
            max_results=max_results,
        )
        ranked_payload.update({
            "status": "success" if results else "error" if errors else "success",
            "query": query_text,
            "queries": query_variants,
            "errors": errors,
            "attempts": attempts,
            "integration_status": self._integration_status(),
        })
        return ranked_payload

    def research(
        self,
        query: str,
        *,
        local_top_k: int = 10,
        web_max_results: int = 10,
        use_vector: bool = False,
        search_mode: str = "package",
        vector_index_name: str = "hacc_corpus",
        vector_index_dir: Optional[Path | str] = None,
        engines: Optional[List[str]] = None,
        domain_filter: Optional[Sequence[str] | str] = None,
        scrape: bool = False,
        include_legal: bool = True,
        legal_max_results: int = 10,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        local_payload = self.search(
            query_text,
            top_k=local_top_k,
            use_vector=use_vector,
            search_mode=search_mode,
            index_name=vector_index_name,
            index_dir=vector_index_dir,
        )
        web_payload = self.discover(
            query_text,
            max_results=web_max_results,
            engines=engines,
            domain_filter=domain_filter,
            scrape=scrape,
        )
        legal_payload = self.discover_legal_authorities(
            query_text,
            max_results=legal_max_results,
        ) if include_legal else {
            "status": "disabled",
            "query": query_text,
            "results": [],
            "result_count": 0,
            "integration_status": self._integration_status(),
        }
        grounding_summary = self._build_research_grounding_summary(
            query_text=query_text,
            local_payload=local_payload,
            web_payload=web_payload,
            legal_payload=legal_payload,
        )
        research_action_queue = self._build_research_action_queue(
            query_text=query_text,
            grounding_summary=grounding_summary,
            web_payload=web_payload,
            legal_payload=legal_payload,
        )
        return {
            "status": "success",
            "query": query_text,
            "query_metadata": {
                "use_vector": bool(use_vector),
                "search_mode": str(search_mode or "auto"),
                "local_top_k": int(local_top_k),
                "web_max_results": int(web_max_results),
                "legal_max_results": int(legal_max_results),
                "vector_index_name": vector_index_name,
                "vector_index_dir": str(Path(vector_index_dir or self.default_index_dir).resolve()),
                "engines": list(engines or []),
                "domain_filter": sorted(self._normalize_domain_filters(domain_filter)),
                "scrape": bool(scrape),
                "include_legal": bool(include_legal),
            },
            "local_search_summary": _summarize_search_payload(
                local_payload,
                requested_mode=str(search_mode or "auto"),
                use_vector=bool(use_vector),
            ),
            "local_chronology_summary": {
                "chronology_ready_result_count": int(local_payload.get("chronology_ready_result_count", 0) or 0),
                "anchor_section_counts": dict(local_payload.get("anchor_section_counts") or {}),
            },
            "research_grounding_summary": grounding_summary,
            "seeded_discovery_plan": dict(grounding_summary.get("seeded_discovery_plan") or {}),
            "research_action_queue": research_action_queue,
            "recommended_next_action": dict(research_action_queue[0]) if research_action_queue else {},
            "local_search": local_payload,
            "web_discovery": web_payload,
            "legal_discovery": legal_payload,
            "integration_status": self._integration_status(),
        }

    def build_grounding_bundle(
        self,
        query: str,
        *,
        top_k: int = 5,
        claim_type: str = "housing_discrimination",
        search_mode: str = "package",
        use_vector: bool = False,
    ) -> Dict[str, Any]:
        query_text = _clean_text(query)
        search_payload = self.search(
            query_text,
            top_k=max(top_k * 5, top_k),
            search_mode=search_mode,
            use_vector=use_vector,
        )
        search_results = list(search_payload.get("results", []) or [])
        reranked_search_results, grounding_query_context, grounding_support_bundle = self._rerank_result_items(
            search_results,
            query_text=query_text,
            claim_type=str(claim_type or "").strip() or "housing_discrimination",
            max_results=max(top_k * 5, top_k),
        )
        if reranked_search_results:
            search_payload["results"] = reranked_search_results
            search_payload["returned_result_count"] = min(
                int(search_payload.get("returned_result_count") or len(reranked_search_results)),
                len(reranked_search_results),
            )
            search_payload["query_context"] = grounding_query_context
            search_payload["support_bundle"] = grounding_support_bundle
            search_payload["reranked_by_orchestrator"] = bool(grounding_support_bundle)
        upload_candidates = self._select_uploadable_results(search_payload, top_k=top_k)
        grounding_overview = self._build_grounding_overview(upload_candidates)
        chronology_analysis = self._build_grounding_chronology_analysis(
            upload_candidates,
            claim_type=str(claim_type or "").strip() or "housing_discrimination",
            query_text=query_text,
        )
        grounding_signals = self._build_grounding_signal_bundle(
            upload_candidates,
            query_text=query_text,
            claim_type=str(claim_type or "").strip() or "housing_discrimination",
            grounding_overview=grounding_overview,
            chronology_analysis=chronology_analysis,
        )
        external_research_bundle = self._build_external_research_bundle(
            query_text=query_text,
            claim_type=str(claim_type or "").strip() or "housing_discrimination",
            max_results=max(3, min(top_k, 5)),
        )
        synthetic_prompts = self._build_synthetic_prompts(
            query_text=query_text,
            claim_type=claim_type,
            upload_candidates=upload_candidates,
            grounding_overview=grounding_overview,
            chronology_analysis=chronology_analysis,
            grounding_signals=grounding_signals,
            external_research_bundle=external_research_bundle,
        )
        mediator_evidence_packets = self._build_mediator_evidence_packets(
            upload_candidates,
            chronology_analysis=chronology_analysis,
            claim_support_temporal_handoff=grounding_signals["claim_support_temporal_handoff"],
        )
        return {
            "status": "success",
            "query": query_text,
            "claim_type": str(claim_type or "").strip() or "housing_discrimination",
            "search_mode": str(search_mode or "auto"),
            "use_vector": bool(use_vector),
            "search_summary": _summarize_search_payload(
                search_payload,
                requested_mode=str(search_mode or "auto"),
                use_vector=bool(use_vector),
            ),
            "search_payload": search_payload,
            "query_context": grounding_query_context,
            "retrieval_support_bundle": grounding_support_bundle,
            "upload_candidates": upload_candidates,
            "evidence_summary": grounding_overview["evidence_summary"],
            "anchor_passages": grounding_overview["anchor_passages"],
            "anchor_sections": grounding_overview["anchor_sections"],
            "mediator_evidence_packets": mediator_evidence_packets,
            "synthetic_prompts": synthetic_prompts,
            "complaint_manager_interfaces": complaint_manager_interfaces(),
            "external_research_bundle": external_research_bundle,
            "chronology_analysis": chronology_analysis,
            "timeline_anchors": chronology_analysis.get("timeline_anchors", []),
            "claim_support_temporal_handoff": grounding_signals["claim_support_temporal_handoff"],
            "drafting_readiness": grounding_signals["drafting_readiness"],
            "document_generation_handoff": grounding_signals["document_generation_handoff"],
            "graph_completeness_signals": grounding_signals["graph_completeness_signals"],
            "document_handoff_summary": grounding_signals["document_generation_handoff"],
            "document_generation": grounding_signals["document_generation_handoff"],
            "graph_analysis": grounding_signals["graph_completeness_signals"],
            "phase_status": grounding_signals["drafting_readiness"],
            "signals": grounding_signals["graph_completeness_signals"],
            "integration_status": self._integration_status(),
        }

    def simulate_evidence_upload(
        self,
        query: str,
        *,
        top_k: int = 5,
        claim_type: str = "housing_discrimination",
        user_id: str = "hacc-grounding",
        search_mode: str = "package",
        use_vector: bool = False,
        db_dir: Optional[Path | str] = None,
        mediator: Any = None,
    ) -> Dict[str, Any]:
        grounding_bundle = self.build_grounding_bundle(
            query,
            top_k=top_k,
            claim_type=claim_type,
            search_mode=search_mode,
            use_vector=use_vector,
        )
        upload_candidates = list(grounding_bundle.get("upload_candidates", []) or [])
        if not upload_candidates:
            return {
                "status": "success",
                "query": _clean_text(query),
                "claim_type": str(claim_type or "").strip() or "housing_discrimination",
                "user_id": str(user_id or "hacc-grounding"),
                "search_summary": grounding_bundle.get("search_summary", {}),
                "upload_count": 0,
                "uploads": [],
                "errors": [],
                "stored_evidence": [],
                "support_summary": {},
                "synthetic_prompts": grounding_bundle.get("synthetic_prompts", {}),
                "retrieval_support_bundle": grounding_bundle.get("retrieval_support_bundle", {}),
                "external_research_bundle": grounding_bundle.get("external_research_bundle", {}),
                "query_context": grounding_bundle.get("query_context", {}),
                "database_paths": {},
                "integration_status": self._integration_status(),
            }

        created_db_dir = False
        db_root: Optional[Path] = None
        if mediator is None:
            try:
                from mediator.mediator import Mediator
            except Exception as exc:
                return {
                    "status": "unavailable",
                    "query": _clean_text(query),
                    "claim_type": str(claim_type or "").strip() or "housing_discrimination",
                    "user_id": str(user_id or "hacc-grounding"),
                    "search_summary": grounding_bundle.get("search_summary", {}),
                    "upload_count": 0,
                    "uploads": [],
                    "errors": [{"stage": "import", "error": str(exc)}],
                    "stored_evidence": [],
                    "support_summary": {},
                    "synthetic_prompts": grounding_bundle.get("synthetic_prompts", {}),
                    "retrieval_support_bundle": grounding_bundle.get("retrieval_support_bundle", {}),
                    "external_research_bundle": grounding_bundle.get("external_research_bundle", {}),
                    "query_context": grounding_bundle.get("query_context", {}),
                    "database_paths": {},
                    "integration_status": self._integration_status(),
                }

            if db_dir is None:
                db_root = Path(tempfile.mkdtemp(prefix="hacc_grounding_"))
                created_db_dir = True
            else:
                db_root = Path(db_dir).resolve()
                db_root.mkdir(parents=True, exist_ok=True)
            mediator = Mediator(
                backends=[],
                evidence_db_path=str(db_root / "evidence.duckdb"),
                legal_authority_db_path=str(db_root / "legal_authorities.duckdb"),
                claim_support_db_path=str(db_root / "claim_support.duckdb"),
            )
            mediator.state.username = str(user_id or "hacc-grounding")
            mediator.state.hashed_username = str(user_id or "hacc-grounding")

        uploads: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for candidate in upload_candidates:
            file_path = str(candidate.get("source_path") or "")
            if not file_path:
                continue
            submission = self._prepare_mediator_submission(candidate)
            path = Path(file_path)
            metadata = {
                "grounding_query": _clean_text(query),
                "source_type": candidate.get("source_type", "repository_evidence"),
                "relative_path": candidate.get("relative_path", ""),
                "snippet": candidate.get("snippet", ""),
                "mime_type": submission["mime_type"],
                "filename": submission["filename"],
                "original_mime_type": submission["original_mime_type"],
                "original_filename": path.name,
                "upload_strategy": submission["upload_strategy"],
            }
            try:
                if submission["upload_strategy"] == "extracted_text_fallback":
                    result = mediator.submit_evidence(
                        data=submission["data"],
                        evidence_type="document",
                        user_id=str(user_id or "hacc-grounding"),
                        description=f"Grounding evidence: {candidate.get('title') or path.name}",
                        claim_type=str(claim_type or "").strip() or "housing_discrimination",
                        claim_element=_clean_text(query),
                        metadata=metadata,
                    )
                else:
                    result = mediator.submit_evidence_file(
                        file_path=file_path,
                        evidence_type="document",
                        user_id=str(user_id or "hacc-grounding"),
                        description=f"Grounding evidence: {candidate.get('title') or path.name}",
                        claim_type=str(claim_type or "").strip() or "housing_discrimination",
                        claim_element=_clean_text(query),
                        metadata=metadata,
                    )
            except Exception as exc:
                errors.append(
                    {
                        "source_path": file_path,
                        "title": candidate.get("title", ""),
                        "error": str(exc),
                    }
                )
                continue
            uploads.append(
                {
                    "source_path": file_path,
                    "title": candidate.get("title", ""),
                    "relative_path": candidate.get("relative_path", ""),
                    "upload_strategy": submission["upload_strategy"],
                    "result": result if isinstance(result, dict) else {"value": str(result)},
                }
            )

        get_user_evidence = getattr(mediator, "get_user_evidence", None)
        stored_evidence = (
            list(get_user_evidence(str(user_id or "hacc-grounding")) or [])
            if callable(get_user_evidence)
            else []
        )
        summarize_claim_support = getattr(mediator, "summarize_claim_support", None)
        support_summary = (
            summarize_claim_support(str(user_id or "hacc-grounding"), str(claim_type or "").strip() or None)
            if callable(summarize_claim_support)
            else {}
        )
        evidence_analysis = {}
        evidence_analysis_hook = getattr(mediator, "evidence_analysis", None)
        analyze_evidence_for_claim = getattr(evidence_analysis_hook, "analyze_evidence_for_claim", None)
        if not callable(analyze_evidence_for_claim):
            analyze_evidence_for_claim = getattr(mediator, "analyze_evidence_for_claim", None)
        if callable(analyze_evidence_for_claim):
            try:
                evidence_analysis = analyze_evidence_for_claim(
                    str(user_id or "hacc-grounding"),
                    str(claim_type or "").strip() or "housing_discrimination",
                )
            except Exception as exc:
                evidence_analysis = {"error": str(exc)}
        database_paths = {
            "evidence_db_path": str(db_root / "evidence.duckdb") if db_root else "",
            "legal_authority_db_path": str(db_root / "legal_authorities.duckdb") if db_root else "",
            "claim_support_db_path": str(db_root / "claim_support.duckdb") if db_root else "",
            "temporary_db_dir": str(db_root) if db_root and created_db_dir else "",
        }
        return {
            "status": "success" if not errors else "partial",
            "query": _clean_text(query),
            "claim_type": str(claim_type or "").strip() or "housing_discrimination",
            "user_id": str(user_id or "hacc-grounding"),
            "search_summary": grounding_bundle.get("search_summary", {}),
            "upload_count": len(uploads),
            "uploads": uploads,
            "errors": errors,
            "stored_evidence": stored_evidence,
            "support_summary": support_summary if isinstance(support_summary, dict) else {"value": support_summary},
            "evidence_analysis": evidence_analysis if isinstance(evidence_analysis, dict) else {"value": evidence_analysis},
            "mediator_evidence_packets": grounding_bundle.get("mediator_evidence_packets", []),
            "synthetic_prompts": grounding_bundle.get("synthetic_prompts", {}),
            "retrieval_support_bundle": grounding_bundle.get("retrieval_support_bundle", {}),
            "external_research_bundle": grounding_bundle.get("external_research_bundle", {}),
            "query_context": grounding_bundle.get("query_context", {}),
            "database_paths": database_paths,
            "integration_status": self._integration_status(),
        }

    def _build_research_grounding_summary(
        self,
        *,
        query_text: str,
        local_payload: Dict[str, Any],
        web_payload: Dict[str, Any],
        legal_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        upload_candidates = self._select_uploadable_results(local_payload, top_k=3)
        grounding_overview = self._build_grounding_overview(upload_candidates)
        chronology_analysis = self._build_grounding_chronology_analysis(
            upload_candidates,
            claim_type="housing_discrimination",
            query_text=query_text,
        )
        grounding_signals = self._build_grounding_signal_bundle(
            upload_candidates,
            query_text=query_text,
            claim_type="housing_discrimination",
            grounding_overview=grounding_overview,
            chronology_analysis=chronology_analysis,
        )
        synthetic_prompts = self._build_synthetic_prompts(
            query_text=query_text,
            claim_type="housing_discrimination",
            upload_candidates=upload_candidates,
            grounding_overview=grounding_overview,
            chronology_analysis=chronology_analysis,
            grounding_signals=grounding_signals,
        )
        seeded_discovery_plan = self._build_seeded_discovery_plan(
            query_text=query_text,
            anchor_sections=grounding_overview.get("anchor_sections", []),
            chronology_analysis=chronology_analysis,
            web_payload=web_payload,
            legal_payload=legal_payload,
        )
        return {
            "upload_ready_candidate_count": len(upload_candidates),
            "recommended_upload_paths": [
                str(item.get("relative_path") or item.get("source_path") or "")
                for item in upload_candidates
                if str(item.get("relative_path") or item.get("source_path") or "").strip()
            ],
            "top_documents": [
                str(item.get("title") or item.get("relative_path") or item.get("source_path") or "")
                for item in upload_candidates
                if str(item.get("title") or item.get("relative_path") or item.get("source_path") or "").strip()
            ],
            "anchor_sections": list(grounding_overview.get("anchor_sections") or []),
            "chronology_ready_result_count": int(local_payload.get("chronology_ready_result_count", 0) or 0),
            "timeline_anchor_count": int(chronology_analysis.get("timeline_anchor_count", 0) or 0),
            "blocker_objectives": list(grounding_signals.get("blocker_objectives") or []),
            "extraction_targets": list(grounding_signals.get("extraction_targets") or []),
            "workflow_phase_priorities": list(grounding_signals.get("workflow_phase_priorities") or []),
            "evidence_upload_form_seed": dict(synthetic_prompts.get("evidence_upload_form_seed") or {}),
            "production_evidence_intake_steps": list(synthetic_prompts.get("production_evidence_intake_steps") or []),
            "mediator_upload_checklist": list(synthetic_prompts.get("mediator_upload_checklist") or []),
            "document_generation_checklist": list(synthetic_prompts.get("document_generation_checklist") or []),
            "court_complaint_synthesis_prompt": str(synthetic_prompts.get("court_complaint_synthesis_prompt") or ""),
            "evidence_upload_simulation_prompt": str(synthetic_prompts.get("evidence_upload_simulation_prompt") or ""),
            "claim_support_temporal_handoff": dict(grounding_signals.get("claim_support_temporal_handoff") or {}),
            "document_generation_handoff": dict(grounding_signals.get("document_generation_handoff") or {}),
            "drafting_readiness": dict(grounding_signals.get("drafting_readiness") or {}),
            "retrieval_support_bundle": dict(local_payload.get("support_bundle") or {}),
            "seeded_discovery_plan": seeded_discovery_plan,
        }

    def _build_seeded_discovery_plan(
        self,
        *,
        query_text: str,
        anchor_sections: Sequence[str],
        chronology_analysis: Dict[str, Any],
        web_payload: Dict[str, Any],
        legal_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        section_query_hints = {
            "grievance_hearing": '"grievance hearing" OR "informal hearing" OR "hearing request"',
            "appeal_rights": '"appeal rights" OR "informal review" OR "written notice"',
            "reasonable_accommodation": '"reasonable accommodation" OR disability OR accommodation',
            "adverse_action": '"adverse action" OR termination OR denial OR "notice of adverse action"',
            "selection_criteria": 'selection OR screening OR criteria OR evaluation',
        }
        resolved_anchor_sections = [str(item).strip() for item in anchor_sections if str(item).strip()]
        query_lines: List[str] = []
        for label in resolved_anchor_sections[:4]:
            hint = section_query_hints.get(label, label.replace("_", " "))
            query_lines.append(f'site:hacc.example {hint} "{query_text}"')
        if not query_lines:
            query_lines.append(f'site:hacc.example "{query_text}" policy notice hearing')

        timeline_anchor_count = int(chronology_analysis.get("timeline_anchor_count", 0) or 0)
        unresolved_temporal_issue_count = int(chronology_analysis.get("unresolved_temporal_issue_count", 0) or 0)
        recommended_domains = self._dedupe_preserve_order(
            [
                urlparse(str(item.get("url") or "")).netloc.lower()
                for item in list(web_payload.get("results") or [])
                if str(item.get("url") or "").strip()
            ]
        )
        return {
            "query_count": len(query_lines),
            "queries": query_lines,
            "recommended_domains": recommended_domains[:8],
            "has_web_results": bool(list(web_payload.get("results") or [])),
            "has_legal_results": bool(list(legal_payload.get("results") or [])),
            "timeline_anchor_count": timeline_anchor_count,
            "unresolved_temporal_issue_count": unresolved_temporal_issue_count,
            "priority": "chronology_first" if unresolved_temporal_issue_count else "upload_and_graph",
        }

    def _build_research_action_queue(
        self,
        *,
        query_text: str,
        grounding_summary: Dict[str, Any],
        web_payload: Dict[str, Any],
        legal_payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        action_queue: List[Dict[str, Any]] = []
        upload_ready_candidate_count = int(grounding_summary.get("upload_ready_candidate_count", 0) or 0)
        recommended_upload_paths = [
            str(item).strip()
            for item in list(grounding_summary.get("recommended_upload_paths") or [])
            if str(item).strip()
        ]
        blocker_objectives = [
            str(item).strip()
            for item in list(grounding_summary.get("blocker_objectives") or [])
            if str(item).strip()
        ]
        seeded_discovery_plan = dict(grounding_summary.get("seeded_discovery_plan") or {})
        if upload_ready_candidate_count:
            action_queue.append(
                {
                    "phase_name": "evidence_upload",
                    "action": "upload_local_repository_evidence",
                    "priority": 100,
                    "description": f"Upload the strongest repository evidence for '{query_text}' into the mediator first.",
                    "recommended_upload_paths": recommended_upload_paths[:5],
                }
            )

        if (
            int(seeded_discovery_plan.get("unresolved_temporal_issue_count", 0) or 0) > 0
            and (
                upload_ready_candidate_count > 0
                or int(grounding_summary.get("timeline_anchor_count", 0) or 0) > 0
            )
        ):
            action_queue.append(
                {
                    "phase_name": "graph_analysis",
                    "action": "fill_chronology_gaps",
                    "priority": 95,
                    "description": "Prioritize dated notices, response timing, and event order before broad drafting.",
                    "blocker_objectives": blocker_objectives[:5],
                    "seeded_queries": list(seeded_discovery_plan.get("queries") or [])[:5],
                }
            )

        if list(seeded_discovery_plan.get("queries") or []):
            action_queue.append(
                {
                    "phase_name": "research",
                    "action": "run_seeded_discovery",
                    "priority": 85,
                    "description": "Expand discovery with complaint-aware seeded CommonCrawl/IPFS queries.",
                    "seeded_queries": list(seeded_discovery_plan.get("queries") or [])[:5],
                    "recommended_domains": list(seeded_discovery_plan.get("recommended_domains") or [])[:8],
                }
            )

        web_results = list(web_payload.get("results") or [])
        if web_results:
            action_queue.append(
                {
                    "phase_name": "research",
                    "action": "review_web_discovery_results",
                    "priority": 70,
                    "description": "Review discovered web materials for additional uploadable policies, notices, or procedures.",
                    "result_count": len(web_results),
                }
            )

        legal_results = list(legal_payload.get("results") or [])
        if legal_results:
            action_queue.append(
                {
                    "phase_name": "document_generation",
                    "action": "review_legal_authorities",
                    "priority": 60,
                    "description": "Use discovered legal authorities to strengthen the complaint theory and document framing.",
                    "result_count": len(legal_results),
                }
            )

        action_queue.sort(
            key=lambda item: (
                -int(item.get("priority", 0) or 0),
                str(item.get("phase_name") or ""),
                str(item.get("action") or ""),
            )
        )
        return action_queue

    def _resolve_vector_indexes(
        self,
        *,
        index_name: str,
        index_dir: Optional[Path | str],
    ) -> List[Dict[str, str]]:
        if index_dir is not None or index_name != "hacc_corpus":
            resolved_dir = str(Path(index_dir or self.default_index_dir).resolve())
            return [{"index_name": index_name, "index_dir": resolved_dir}]

        preferred_candidates = [
            {"index_name": "hacc_policy_graph", "index_dir": str(self.default_embedding_dir)},
            {"index_name": "hacc_text_chunks", "index_dir": str(self.default_embedding_dir)},
            {"index_name": "hacc_corpus", "index_dir": str(self.default_index_dir)},
        ]
        available_candidates: List[Dict[str, str]] = []
        for candidate in preferred_candidates:
            manifest_path = Path(candidate["index_dir"]) / f"{candidate['index_name']}.manifest.json"
            if manifest_path.exists():
                available_candidates.append(candidate)

        return available_candidates or preferred_candidates

    def _has_preferred_vector_index(
        self,
        *,
        index_name: str,
        index_dir: Optional[Path | str],
    ) -> bool:
        if search_vector_index is None or not VECTOR_STORE_AVAILABLE:
            return False
        candidates = self._resolve_vector_indexes(index_name=index_name, index_dir=index_dir)
        for candidate in candidates:
            manifest_path = Path(candidate["index_dir"]) / f"{candidate['index_name']}.manifest.json"
            if manifest_path.exists():
                return True
        return False

    def _load_parsed_documents(self) -> List[CorpusDocument]:
        if not self.parse_manifest_path.exists():
            return []

        manifest = _safe_json_load(self.parse_manifest_path)
        entries = manifest.get("parsed_documents") or []
        documents: List[CorpusDocument] = []
        for entry in entries:
            raw_text_path = str(entry.get("parsed_text_path") or "").strip()
            if not raw_text_path:
                continue
            text_path = Path(raw_text_path).expanduser()
            if not text_path.is_absolute():
                text_path = (self.repo_root / text_path).resolve()
            if not text_path.exists() or not text_path.is_file():
                continue

            text = text_path.read_text(encoding="utf-8", errors="ignore")
            metadata_path = text_path.with_suffix(".json")
            sidecar = _safe_json_load(metadata_path) if metadata_path.exists() else {}
            title = self._infer_title(text, fallback=Path(str(entry.get("pdf_path") or text_path)).stem)
            source_id = text_path.stem
            graph_payload = self._extract_graph_payload(text=text, source_id=source_id, title=title, source_path=text_path)
            chronology_metadata = self._build_document_chronology_metadata(
                text,
                title=title,
                source_path=str(text_path),
                source_type="parsed_document",
            )
            documents.append(
                CorpusDocument(
                    document_id=source_id,
                    title=title,
                    text=text,
                    source_type="parsed_document",
                    source_path=str(text_path),
                    metadata={
                        **entry,
                        **sidecar,
                        "graph_status": graph_payload.get("status", "unavailable"),
                        **chronology_metadata,
                    },
                    rules=[],
                    entities=list(graph_payload.get("entities", []) or []),
                    relationships=list(graph_payload.get("relationships", []) or []),
                )
            )
        return documents

    def _load_repository_evidence_documents(self) -> List[CorpusDocument]:
        documents: List[CorpusDocument] = []
        seen_paths: set[str] = set()
        for path in self._iter_repository_evidence_paths():
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            document = self._ingest_repository_evidence_document(path)
            if document is None:
                continue
            documents.append(document)
        return documents

    def _ingest_repository_evidence_document(self, path: Path) -> Optional[CorpusDocument]:
        try:
            relative_path = path.relative_to(self.repo_root)
        except ValueError:
            return None

        ingest_payload: Dict[str, Any] = {}
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""

        if not _clean_text(text) and ingest_local_document is not None:
            try:
                ingest_payload = ingest_local_document(
                    path,
                    metadata={
                        "title": relative_path.stem.replace("_", " "),
                        "relative_path": relative_path.as_posix(),
                        "source_type": "repository_evidence",
                    },
                    output_dir=self.repository_ingest_dir,
                )
            except Exception:
                ingest_payload = {}

        if not _clean_text(text):
            text = str(ingest_payload.get("text") or "")
        if not _clean_text(text):
            return None

        parse_payload = ingest_payload.get("parse") if isinstance(ingest_payload.get("parse"), dict) else {}
        parse_metadata = parse_payload.get("metadata") if isinstance(parse_payload.get("metadata"), dict) else {}
        parse_summary = parse_payload.get("summary") if isinstance(parse_payload.get("summary"), dict) else {}
        if not parse_summary:
            parse_summary = {
                "status": "success" if _clean_text(text) else "empty",
                "text_length": len(text),
                "line_count": len(text.splitlines()),
                "ingest_mode": "direct_text_read",
            }
        title = self._infer_title(text, fallback=relative_path.stem.replace("_", " "))
        source_id = f"repo::{relative_path.as_posix()}"
        graph_payload = self._extract_graph_payload(text=text, source_id=source_id, title=title, source_path=path)
        rule_like_facts = self._graph_facts_to_rule_like_records(graph_payload)
        chronology_metadata = self._build_document_chronology_metadata(
            text,
            title=title,
            source_path=str(path),
            source_type="repository_evidence",
        )
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = len(text.encode("utf-8", errors="ignore"))

        quality_payload = parse_metadata.get("parse_quality") if isinstance(parse_metadata.get("parse_quality"), dict) else {}
        return CorpusDocument(
            document_id=source_id,
            title=title,
            text=text,
            source_type="repository_evidence",
            source_path=str(path),
            metadata={
                "relative_path": relative_path.as_posix(),
                "category": relative_path.parts[0] if len(relative_path.parts) > 1 else "root",
                "size_bytes": size_bytes,
                "graph_status": graph_payload.get("status", "unavailable"),
                "graph_entity_count": len(graph_payload.get("entities", []) or []),
                "graph_relationship_count": len(graph_payload.get("relationships", []) or []),
                "document_ingest_status": str(ingest_payload.get("status") or ("success" if text else "empty")),
                "content_type": str(ingest_payload.get("content_type") or parse_metadata.get("mime_type") or ""),
                "extraction_method": str(ingest_payload.get("extraction_method") or parse_metadata.get("extraction_method") or ""),
                "parse_status": str(parse_payload.get("status") or ""),
                "parse_summary": dict(parse_summary),
                "parse_metadata": dict(parse_metadata),
                "quality_tier": str(quality_payload.get("quality_tier") or ""),
                "quality_score": float(quality_payload.get("quality_score", 0.0) or 0.0),
                "parsed_text_path": str(ingest_payload.get("parsed_text_path") or ""),
                "metadata_path": str(ingest_payload.get("metadata_path") or ""),
                "checksum": str(ingest_payload.get("checksum") or ""),
                "source_record_id": str(ingest_payload.get("id") or ""),
                **chronology_metadata,
            },
            rules=rule_like_facts,
            entities=list(graph_payload.get("entities", []) or []),
            relationships=list(graph_payload.get("relationships", []) or []),
        )

    def _iter_repository_evidence_paths(self) -> Iterable[Path]:
        try:
            for child in sorted(self.repo_root.iterdir()):
                if child.is_file() and not self._should_skip_repository_evidence_path(child):
                    yield child
        except OSError:
            return

        for dir_name in REPOSITORY_EVIDENCE_RECURSIVE_DIRS:
            root = (self.repo_root / dir_name).resolve()
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and not self._should_skip_repository_evidence_path(path):
                    yield path

    def _should_skip_repository_evidence_path(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.repo_root)
        except ValueError:
            return True

        if path.name.startswith("."):
            return True
        if path.suffix.lower() not in REPOSITORY_EVIDENCE_EXTENSIONS:
            return True
        if any(part in REPOSITORY_EVIDENCE_SKIP_PARTS for part in relative.parts):
            return True
        if relative.parts[:2] == ("research_results", "documents"):
            return True
        try:
            if path.stat().st_size > REPOSITORY_EVIDENCE_MAX_BYTES:
                return True
        except OSError:
            return True
        return False

    def _select_uploadable_results(self, payload: Dict[str, Any], *, top_k: int) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen_paths: set[str] = set()
        query_text = _clean_text(str(payload.get("query") or ""))
        for item in list(payload.get("results", []) or []):
            source_path = str(item.get("source_path") or "").strip()
            if not source_path:
                continue
            path = Path(source_path)
            if not path.exists() or not path.is_file():
                continue
            resolved_path = str(path.resolve())
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            try:
                relative_path = path.resolve().relative_to(self.repo_root).as_posix()
            except ValueError:
                relative_path = path.name
            candidates.append(
                {
                    "document_id": str(item.get("document_id") or ""),
                    "title": str(item.get("title") or path.name),
                    "source_type": str(item.get("source_type") or "document"),
                    "source_path": resolved_path,
                    "relative_path": relative_path,
                    "score": float(item.get("score", 0.0) or 0.0),
                    "snippet": str(item.get("snippet") or "")[:500],
                    "metadata": dict(item.get("metadata") or {}),
                    "matched_rules": list(item.get("matched_rules") or []),
                    "matched_entities": list(item.get("matched_entities") or []),
                    "parse_summary": dict((item.get("metadata") or {}).get("parse_summary") or {}),
                    "graph_status": str((item.get("metadata") or {}).get("graph_status") or ""),
                    "selection_priority": self._upload_candidate_priority_score(item, query_text=query_text),
                }
            )
        source_rank = {
            "repository_evidence": 0,
            "parsed_document": 1,
            "knowledge_graph": 2,
        }
        candidates.sort(
            key=lambda item: (
                -float(item.get("selection_priority", 0.0) or 0.0),
                -float(item.get("score", 0.0) or 0.0),
                source_rank.get(str(item.get("source_type") or ""), 9),
                str(item.get("title") or ""),
            )
        )
        return candidates[:top_k]

    def _upload_candidate_priority_score(self, item: Dict[str, Any], *, query_text: str) -> float:
        if not query_text:
            return 0.0
        query_tokens = _semantic_tokens(query_text)
        chronology_intent = bool(query_tokens & _CHRONOLOGY_QUERY_TOKENS)
        if not chronology_intent:
            return 0.0

        priority = 0.0
        source_type = str(item.get("source_type") or "").strip().lower()
        if source_type == "repository_evidence":
            priority += 3.0
        elif source_type == "parsed_document":
            priority += 2.0

        evidence_fragments = [
            _clean_text(str(item.get("title") or "")),
            _clean_text(str(item.get("snippet") or "")),
        ]
        for rule in list(item.get("matched_rules") or [])[:5]:
            evidence_fragments.append(_clean_text(str(rule.get("text") or "")))
            evidence_fragments.append(_clean_text(str(rule.get("section_title") or "")))
        for entity in list(item.get("matched_entities") or [])[:5]:
            evidence_fragments.append(_clean_text(str(entity.get("name") or "")))
        combined_text = " ".join(fragment for fragment in evidence_fragments if fragment).lower()
        anchor_sections = self._candidate_anchor_sections(item)

        cue_hits = sum(1 for cue in _CASE_EVIDENCE_PRIORITY_CUES if cue in combined_text)
        procedural_hits = sum(1 for cue in _UPLOAD_CANDIDATE_PROCEDURAL_TERMS if cue in combined_text)
        action_hits = sum(1 for cue in _CASE_TIMELINE_ACTION_CUES if cue in combined_text)
        party_hits = sum(1 for cue in _CASE_TIMELINE_PARTY_CUES if cue in combined_text)
        hacc_hits = combined_text.count("hacc")
        if cue_hits:
            priority += min(6.0, cue_hits * 1.75)
        if procedural_hits:
            priority += min(4.0, procedural_hits * 1.0)
        if action_hits:
            priority += min(4.0, action_hits * 1.5)
        if party_hits:
            priority += min(2.0, party_hits * 0.5)
        if anchor_sections:
            priority += min(3.0, len(anchor_sections) * 1.25)
        if hacc_hits:
            priority += min(2.5, hacc_hits * 0.75)

        chronology_summary = dict((item.get("chronology_summary") or (item.get("metadata") or {}).get("chronology_summary") or {}))
        if int(chronology_summary.get("timeline_anchor_count", 0) or 0) > 0:
            priority += 1.5

        title_lower = str(item.get("title") or "").strip().lower()
        if any(term in title_lower for term in ("policy", "plan", "program")) and not cue_hits and not action_hits:
            priority -= 1.0
        if any(marker in combined_text for marker in _UPLOAD_CANDIDATE_NOISE_MARKERS):
            priority -= 8.0
        relative_path_lower = str(item.get("relative_path") or item.get("source_path") or "").strip().lower()
        if source_type == "repository_evidence":
            if any(term in relative_path_lower for term in _UPLOAD_CANDIDATE_DOCUMENTATION_PATH_TERMS):
                priority -= 4.5
            if any(marker in combined_text for marker in _UPLOAD_CANDIDATE_DOCUMENTATION_MARKERS):
                priority -= 6.0
            if any(term in title_lower for term in _UPLOAD_CANDIDATE_ANALYSIS_TITLE_TERMS):
                priority -= 6.0
            root_level_repo_file = "/" not in relative_path_lower and relative_path_lower.endswith((".md", ".txt", ".html", ".htm", ".json"))
            if root_level_repo_file and any(term in relative_path_lower for term in _UPLOAD_CANDIDATE_REPOSITORY_SUMMARY_PATH_TERMS):
                priority -= 5.0
        elif any(term in title_lower for term in _UPLOAD_CANDIDATE_ANALYSIS_TITLE_TERMS) and not anchor_sections:
            priority -= 5.0
        if not hacc_hits and not anchor_sections:
            priority -= 2.5
        if not anchor_sections and cue_hits == 0:
            priority -= 3.0
        if procedural_hits == 0:
            priority -= 4.0

        return priority

    def _prepare_mediator_submission(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        source_path = str(candidate.get("source_path") or "").strip()
        path = Path(source_path)
        original_content_type = str((candidate.get("metadata") or {}).get("content_type") or _detect_content_type(path))
        upload_filename = path.name or str(candidate.get("title") or "evidence").strip() or "evidence"
        extracted_text = self._resolve_candidate_upload_text(candidate)

        if original_content_type == "application/pdf" and _clean_text(extracted_text):
            if "." not in upload_filename:
                upload_filename = f"{upload_filename}.txt"
            return {
                "upload_strategy": "extracted_text_fallback",
                "data": extracted_text.encode("utf-8"),
                "mime_type": "text/plain",
                "filename": upload_filename,
                "original_mime_type": original_content_type,
            }

        return {
            "upload_strategy": "file",
            "data": None,
            "mime_type": original_content_type,
            "filename": upload_filename,
            "original_mime_type": original_content_type,
        }

    def _resolve_candidate_upload_text(self, candidate: Dict[str, Any]) -> str:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        parsed_text_path = str(metadata.get("parsed_text_path") or "").strip()
        if parsed_text_path:
            path = Path(parsed_text_path)
            if not path.is_absolute():
                path = (self.repo_root / path).resolve()
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            if _clean_text(text):
                return text

        source_path = str(candidate.get("source_path") or "").strip()
        document_id = str(candidate.get("document_id") or "").strip()
        for document in self.load_corpus():
            if document_id and document.document_id == document_id and _clean_text(document.text):
                return document.text
            if source_path and document.source_path == source_path and _clean_text(document.text):
                return document.text
        return ""

    def _build_mediator_evidence_packets(
        self,
        upload_candidates: Sequence[Dict[str, Any]],
        *,
        chronology_analysis: Optional[Dict[str, Any]] = None,
        claim_support_temporal_handoff: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        packets: List[Dict[str, Any]] = []
        timeline_anchors = [
            dict(item)
            for item in list((chronology_analysis or {}).get("timeline_anchors") or [])
            if isinstance(item, dict)
        ]
        handoff_payload = dict(claim_support_temporal_handoff or {})
        for candidate in upload_candidates:
            source_path = str(candidate.get("source_path") or "").strip()
            if not source_path:
                continue
            path = Path(source_path)
            if not path.exists() or not path.is_file():
                continue
            submission = self._prepare_mediator_submission(candidate)
            document_text = self._resolve_candidate_upload_text(candidate)
            packet_timeline_anchors = [
                anchor
                for anchor in timeline_anchors
                if str(anchor.get("source_path") or "").strip() == source_path
            ]
            packets.append(
                {
                    "document_label": str(candidate.get("title") or path.name),
                    "source_path": source_path,
                    "relative_path": str(candidate.get("relative_path") or path.name),
                    "filename": submission["filename"],
                    "mime_type": submission["mime_type"],
                    "document_text": self._truncate_seed_packet_text(document_text),
                    "timeline_anchors": packet_timeline_anchors,
                    "metadata": {
                        "source_type": str(candidate.get("source_type") or "repository_evidence"),
                        "relative_path": str(candidate.get("relative_path") or path.name),
                        "anchor_sections": self._candidate_anchor_sections(candidate),
                        "parse_summary": dict(candidate.get("parse_summary") or {}),
                        "graph_status": str(candidate.get("graph_status") or ""),
                        "original_mime_type": submission["original_mime_type"],
                        "original_filename": path.name,
                        "upload_strategy": submission["upload_strategy"],
                        "claim_support_temporal_handoff": handoff_payload,
                        "timeline_anchor_count": len(packet_timeline_anchors),
                    },
                }
            )
        return packets

    def _build_synthetic_prompts(
        self,
        *,
        query_text: str,
        claim_type: str,
        upload_candidates: Sequence[Dict[str, Any]],
        grounding_overview: Optional[Dict[str, Any]] = None,
        chronology_analysis: Optional[Dict[str, Any]] = None,
        grounding_signals: Optional[Dict[str, Any]] = None,
        external_research_bundle: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        grounding_overview = dict(grounding_overview or {})
        chronology_analysis = dict(chronology_analysis or {})
        grounding_signals = dict(grounding_signals or {})
        external_research_bundle = dict(external_research_bundle or {})
        temporal_handoff = dict(grounding_signals.get("claim_support_temporal_handoff") or {})
        drafting_readiness = dict(grounding_signals.get("drafting_readiness") or {})
        document_generation_handoff = dict(grounding_signals.get("document_generation_handoff") or {})
        web_discovery = dict(external_research_bundle.get("web_discovery") or {})
        legal_authorities = dict(external_research_bundle.get("legal_authorities") or {})
        prompt_web_titles = _ordered_unique_strings(
            [
                _prompt_web_research_display_text(item)
                for item in list(web_discovery.get("results") or [])
                if isinstance(item, dict) and _is_relevant_prompt_web_research_item(item)
            ]
        )[:3]
        prompt_legal_titles = _ordered_unique_strings(
            [
                _prompt_legal_research_display_text(item)
                for item in list(legal_authorities.get("results") or [])
                if isinstance(item, dict) and _is_relevant_prompt_legal_research_item(item)
            ]
        )[:3]
        blocker_objectives = [str(item) for item in list(grounding_signals.get("blocker_objectives") or []) if str(item)]
        extraction_targets = [str(item) for item in list(grounding_signals.get("extraction_targets") or []) if str(item)]
        workflow_phase_priorities = [
            str(item)
            for item in list(grounding_signals.get("workflow_phase_priorities") or GROUNDING_WORKFLOW_PHASE_PRIORITIES)
            if str(item)
        ]
        upload_prompts: List[Dict[str, Any]] = []
        upload_questions: List[str] = []
        evidence_titles: List[str] = []
        for index, candidate in enumerate(upload_candidates, 1):
            title = str(candidate.get("title") or candidate.get("relative_path") or f"evidence_{index}")
            snippet = _clean_text(str(candidate.get("snippet") or ""))
            anchor_sections = self._candidate_anchor_sections(candidate)
            evidence_titles.append(title)
            anchor_note = f" Anchor sections: {', '.join(anchor_sections)}." if anchor_sections else ""
            upload_questions.append(
                f"Upload {title} and identify the date, sender or author, recipients, and the exact fact it proves for '{query_text}'.{anchor_note}"
            )
            upload_prompts.append(
                {
                    "prompt_id": f"evidence_upload_{index}",
                    "prompt_type": "evidence_upload",
                    "title": title,
                    "source_path": str(candidate.get("source_path") or ""),
                    "relative_path": str(candidate.get("relative_path") or ""),
                    "anchor_sections": anchor_sections,
                    "text": (
                        f"Upload the evidence file '{candidate.get('relative_path') or candidate.get('source_path')}' "
                        f"and explain how it supports a {claim_type} complaint about '{query_text}'. "
                        f"Focus on the most relevant language: {snippet or 'Describe the relevant sections in the document.'}"
                        f"{anchor_note}"
                    ),
                }
            )

        anchor_sections = [str(item) for item in list(grounding_overview.get("anchor_sections") or []) if str(item)]
        anchor_passages = list(grounding_overview.get("anchor_passages") or [])
        evidence_summary = str(grounding_overview.get("evidence_summary") or "").strip()
        anchor_note = f" Prioritize these anchor sections: {', '.join(anchor_sections)}." if anchor_sections else ""
        external_research_note = ""
        if prompt_web_titles:
            external_research_note += f" Review these web evidence leads: {', '.join(prompt_web_titles)}."
        if prompt_legal_titles:
            external_research_note += f" Review these legal or caselaw authorities: {', '.join(prompt_legal_titles)}."
        chronology_note = ""
        chronology_summary = dict(chronology_analysis.get("chronology_summary") or {})
        timeline_consistency_summary = dict(chronology_analysis.get("timeline_consistency_summary") or {})
        unresolved_temporal_issue_count = int(temporal_handoff.get("unresolved_temporal_issue_count", 0) or 0)
        chronology_task_count = int(temporal_handoff.get("chronology_task_count", 0) or 0)
        if unresolved_temporal_issue_count or chronology_task_count:
            chronology_note = " Treat chronology as incomplete until uploaded evidence or testimony supplies dates, actor sequence, and decision-response timing."
        if timeline_consistency_summary and not bool(timeline_consistency_summary.get("partial_order_ready")):
            chronology_note += " Keep chronology-sensitive allegations provisional until ordering and anchor consistency are resolved."
        chatbot_prompt = (
            f"Ground the complaint chatbot in the uploaded repository evidence for '{query_text}'. "
            f"Use the uploaded materials ({', '.join(evidence_titles) if evidence_titles else 'uploaded evidence'}) as factual grounding, "
            "ask the user to connect each document to case-specific events, and identify missing timeline, actor, harm, and remedy facts."
            f"{anchor_note}{chronology_note}{external_research_note}"
        )
        mediator_prompt = (
            f"Evaluate each uploaded evidence item for a {claim_type} complaint about '{query_text}'. "
            "For every document, determine what claim element it supports, what facts it proves directly, what facts remain missing, "
            "and what follow-up questions the mediator should ask before drafting a complaint."
            f"{anchor_note}{chronology_note}{external_research_note}"
        )
        production_prompt = (
            f"A user uploads repository evidence for '{query_text}'. Save each file into the complaint-generator evidence store, "
            "extract factual support from the parsed document, and route the uploaded materials through mediator evidence analysis "
            "before drafting or revising a complaint."
            f"{external_research_note}"
        )
        mediator_questions = [
            "Which uploaded records directly prove dates, notice timing, hearing requests, or decision responses?",
            "Which uploaded records identify the HACC staff or decision-makers involved in each event?",
            "Which uploaded records should be converted into exhibits and linked to claim-support allegations?",
        ]
        document_generation_prompt = (
            f"Promote uploaded evidence for '{query_text}' into chronology anchors, claim-support mappings, exhibit descriptions, and formal allegations. "
            "Use the uploaded records and policy anchors together so the complaint draft stays grounded in provable facts and source-linked exhibits."
        )
        court_complaint_synthesis_prompt = (
            f"Synthesize a court-ready complaint for '{query_text}' by combining uploaded evidence, mediator findings, chronology anchors, "
            "claim-support handoff metadata, and exhibit descriptions. Preserve source links, identify unresolved proof gaps, and keep chronology-sensitive claims conditional when anchors remain incomplete."
            f"{external_research_note}"
        )
        evidence_upload_simulation_prompt = (
            f"Simulate a production evidence upload for '{query_text}': ingest each repository-backed file into the evidence store, "
            "extract dated events and actor-role facts, run mediator evaluation, and feed the resulting packets into complaint synthesis."
        )
        production_evidence_intake_steps = [
            "Upload the strongest case-specific notices, emails, hearing requests, decisions, and policy excerpts first.",
            "Store each uploaded file in the complaint-generator evidence layer with source path, claim type, and upload strategy metadata.",
            "Run mediator evidence analysis to map each upload to claim elements, timeline anchors, and missing proof bundles.",
            "Use the grounded evidence packets and chronology handoff to synthesize allegations, exhibits, and formal complaint sections.",
        ]
        mediator_upload_checklist = [
            "Identify what exact fact each uploaded file proves.",
            "Extract dates, actor names or roles, and decision-response timing from each uploaded record.",
            "Mark which claim element each upload supports, and which proof gaps remain unresolved.",
        ]
        if blocker_objectives:
            mediator_upload_checklist.append(
                f"Prioritize unresolved objectives: {', '.join(blocker_objectives)}."
            )
        document_generation_checklist = [
            "Promote uploaded evidence into chronology anchors and exhibit-ready summaries.",
            "Link grounded documents to claim-support allegations and factual paragraphs before broad drafting.",
        ]
        if extraction_targets:
            document_generation_checklist.append(
                f"Target these extraction lanes: {', '.join(extraction_targets)}."
            )
        intake_questions = [
            "What happened, and what adverse action did HACC take or threaten to take?",
            "When did the key events happen, including the complaint, notice, hearing or review request, and any denial or termination decision?",
            "Who at HACC made, communicated, or carried out each decision?",
            "What written notice, grievance, informal review, hearing, or appeal rights were provided, requested, denied, or ignored?",
            "What housing harm resulted, such as denial of assistance, termination, loss of voucher, delay, extra expense, or risk of displacement?",
            "What remedy are you seeking now?",
        ]
        intake_questionnaire_prompt = (
            f"Before drafting a {claim_type} complaint about '{query_text}', collect concrete case facts from the user. "
            f"Use the uploaded materials ({', '.join(evidence_titles) if evidence_titles else 'uploaded evidence'}) to anchor the questions, "
            "and ask for the following details in plain language:\n- "
            + "\n- ".join(intake_questions)
            + (f"\n- Anchor the intake to these policy sections: {', '.join(anchor_sections)}" if anchor_sections else "")
        )
        selected_upload_candidates = [
            {
                "title": str(candidate.get("title") or "").strip(),
                "source_type": str(candidate.get("source_type") or "").strip(),
                "relative_path": str(candidate.get("relative_path") or "").strip(),
                "selection_priority": float(candidate.get("selection_priority", 0.0) or 0.0),
                "anchor_sections": self._candidate_anchor_sections(candidate),
            }
            for candidate in upload_candidates[:5]
        ]
        return {
            "evidence_upload_prompts": upload_prompts,
            "evidence_upload_prompt": upload_prompts[0]["text"] if upload_prompts else production_prompt,
            "evidence_upload_questions": upload_questions,
            "complaint_chatbot_prompt": chatbot_prompt,
            "mediator_evaluation_prompt": mediator_prompt,
            "mediator_evidence_review_prompt": mediator_prompt,
            "production_upload_prompt": production_prompt,
            "document_generation_prompt": document_generation_prompt,
            "court_complaint_synthesis_prompt": court_complaint_synthesis_prompt,
            "evidence_upload_simulation_prompt": evidence_upload_simulation_prompt,
            "production_evidence_intake_steps": production_evidence_intake_steps,
            "mediator_upload_checklist": mediator_upload_checklist,
            "document_generation_checklist": document_generation_checklist,
            "evidence_upload_form_seed": {
                "claim_type": str(claim_type or "").strip() or "housing_discrimination",
                "grounding_query": query_text,
                "anchor_sections": anchor_sections,
                "timeline_anchor_count": int(chronology_summary.get("timeline_anchor_count", 0) or 0),
                "recommended_files": evidence_titles[:5],
                "selected_upload_candidates": selected_upload_candidates,
                "blocker_objectives": blocker_objectives,
                "extraction_targets": extraction_targets,
            },
            "intake_questionnaire_prompt": intake_questionnaire_prompt,
            "intake_questions": intake_questions,
            "mediator_questions": mediator_questions,
            "workflow_phase_priorities": workflow_phase_priorities,
            "blocker_objectives": blocker_objectives,
            "extraction_targets": extraction_targets,
            "evidence_summary": evidence_summary,
            "anchor_sections": anchor_sections,
            "anchor_passages": anchor_passages,
            "external_research_bundle": external_research_bundle,
            "complaint_manager_interfaces": complaint_manager_interfaces(),
            "web_evidence_research_prompt": (
                f"Search for internet evidence about '{query_text}' that can corroborate the uploaded facts, and rank results by evidentiary usefulness."
                + (f" Start with: {', '.join(prompt_web_titles)}." if prompt_web_titles else "")
            ),
            "legal_authority_research_prompt": (
                f"Search for statutes, regulations, HUD guidance, and caselaw relevant to '{query_text}' and the {claim_type} theory."
                + (f" Start with: {', '.join(prompt_legal_titles)}." if prompt_legal_titles else "")
            ),
            "timeline_anchors": chronology_analysis.get("timeline_anchors", []),
            "timeline_consistency_summary": timeline_consistency_summary,
            "claim_support_temporal_handoff": temporal_handoff,
            "drafting_readiness": drafting_readiness,
            "document_generation_handoff": document_generation_handoff,
        }

    def _build_external_research_bundle(
        self,
        *,
        query_text: str,
        claim_type: str,
        max_results: int = 5,
    ) -> Dict[str, Any]:
        query_plan = self._external_research_query_plan(query_text, claim_type=claim_type)
        web_queries = list(query_plan.get("web_queries") or [query_text])[:6]
        legal_queries = list(query_plan.get("legal_queries") or [query_text])[:6]
        preferred_web_domains = self._preferred_external_web_domains(claim_type)
        web_attempts: List[Dict[str, Any]] = []
        for candidate_query in web_queries:
            filtered_payload = self.discover(
                candidate_query,
                max_results=max_results,
                domain_filter=preferred_web_domains or None,
                scrape=False,
            )
            web_attempts.append(filtered_payload)
            if int(filtered_payload.get("result_count", len(list(filtered_payload.get("results") or []))) or 0) <= 0:
                web_attempts.append(
                    self.discover(candidate_query, max_results=max_results, scrape=False)
                )
        legal_attempts = [
            self.discover_legal_authorities(candidate_query, max_results=max_results)
            for candidate_query in legal_queries
        ]
        web_payload = self._aggregate_external_discovery_results(
            web_attempts,
            result_key="results",
            dedupe_keys=("url", "title"),
            max_results=max_results,
        )
        legal_payload = self._aggregate_external_discovery_results(
            legal_attempts,
            result_key="results",
            dedupe_keys=("citation", "title", "url"),
            max_results=max_results,
        )
        web_payload = self._rank_external_research_payload(
            web_payload,
            query_text=query_text,
            claim_type=claim_type,
            result_kind="web",
            max_results=max_results,
        )
        legal_payload = self._rank_external_research_payload(
            legal_payload,
            query_text=query_text,
            claim_type=claim_type,
            result_kind="legal",
            max_results=max_results,
        )
        promoted_legal_payload = self._promote_web_results_to_legal_authorities(
            web_payload,
            max_results=max_results,
        )
        if int(promoted_legal_payload.get("result_count", 0) or 0) > 0:
            merged_legal_payload = self._aggregate_external_discovery_results(
                [legal_payload, promoted_legal_payload],
                result_key="results",
                dedupe_keys=("citation", "title", "url"),
                max_results=max(max_results * 3, max_results),
            )
            merged_legal_payload["attempts"] = list(legal_payload.get("attempts") or []) + list(
                promoted_legal_payload.get("attempts") or []
            )
            legal_payload = self._rank_external_research_payload(
                merged_legal_payload,
                query_text=query_text,
                claim_type=claim_type,
                result_kind="legal",
                max_results=max_results,
            )
        web_payload.update({
            "query": query_text,
            "queries": web_queries,
            "preferred_domain_filter": preferred_web_domains,
        })
        legal_payload.update({
            "query": query_text,
            "queries": legal_queries,
        })
        top_web_titles = [
            str(item.get("title") or item.get("url") or "").strip()
            for item in list(web_payload.get("results") or [])[:max_results]
            if str(item.get("title") or item.get("url") or "").strip()
        ]
        top_legal_titles = [
            _legal_summary_display_text(item)
            for item in list(legal_payload.get("results") or [])[:max_results]
            if _legal_summary_display_text(item)
        ]
        return {
            "query": query_text,
            "claim_type": claim_type,
            "query_plan": query_plan,
            "web_discovery": web_payload,
            "legal_authorities": legal_payload,
            "summary": {
                "web_result_count": int(web_payload.get("result_count", len(list(web_payload.get("results") or []))) or 0),
                "legal_result_count": int(legal_payload.get("result_count", len(list(legal_payload.get("results") or []))) or 0),
                "top_web_titles": top_web_titles,
                "top_legal_titles": top_legal_titles,
            },
        }

    def _rank_external_research_payload(
        self,
        payload: Dict[str, Any],
        *,
        query_text: str,
        claim_type: str,
        result_kind: str,
        max_results: int,
    ) -> Dict[str, Any]:
        ranked_results: List[Dict[str, Any]] = []
        for item in list(payload.get("results") or []):
            if not isinstance(item, dict):
                continue
            ranked_results.append(
                self._score_external_research_result(
                    dict(item),
                    query_text=query_text,
                    claim_type=claim_type,
                    result_kind=result_kind,
                )
            )
        ranked_results = [
            item for item in ranked_results
            if not bool(item.get("research_relevance_blocked"))
        ]
        ranked_results.sort(
            key=lambda item: (
                -float(item.get("research_priority_score", 0.0) or 0.0),
                _clean_text(str(item.get("title") or item.get("citation") or item.get("url") or "")),
            )
        )
        ranked_payload = dict(payload or {})
        ranked_payload["results"] = ranked_results[:max_results]
        ranked_payload["result_count"] = len(ranked_payload["results"])
        return ranked_payload

    def _score_external_research_result(
        self,
        item: Dict[str, Any],
        *,
        query_text: str,
        claim_type: str,
        result_kind: str,
    ) -> Dict[str, Any]:
        claim_hints = dict(EXTERNAL_RESEARCH_HINTS_BY_CLAIM.get(str(claim_type or "").strip().lower()) or {})
        preferred_domains = self._preferred_external_web_domains(claim_type)
        evidence_text = " ".join(
            fragment
            for fragment in (
                str(item.get("title") or ""),
                str(item.get("citation") or ""),
                str(item.get("summary") or ""),
                str(item.get("snippet") or ""),
                str(item.get("description") or ""),
                str(item.get("url") or ""),
                str(item.get("authority_source") or ""),
            )
            if _clean_text(fragment)
        )
        evidence_tokens = _semantic_tokens(evidence_text)
        query_tokens = _semantic_tokens(query_text)
        chronology_hits = sorted(
            token for token in _CHRONOLOGY_QUERY_TOKENS
            if token in evidence_tokens
        )
        claim_hint_tokens = _semantic_tokens(" ".join(str(value) for value in list(claim_hints.get(result_kind) or [])))
        matched_claim_tokens = sorted(token for token in claim_hint_tokens if token in evidence_tokens)
        matched_query_tokens = sorted(token for token in query_tokens if token in evidence_tokens)
        housing_context = _external_research_has_housing_context(evidence_text)
        procedural_context = _external_research_has_procedural_context(evidence_text)
        grievance_process_fit = _external_research_has_grievance_process_fit(evidence_text)
        strong_legal_citation = _external_research_has_strong_legal_citation(evidence_text)
        score = float(len(matched_query_tokens))
        score += 1.5 * float(len(matched_claim_tokens))
        score += 1.0 * float(len(chronology_hits))

        source_text = evidence_text.lower()
        reasons: List[str] = []
        blocked = False
        if matched_query_tokens:
            reasons.append(f"matched query terms: {', '.join(matched_query_tokens[:6])}")
        if matched_claim_tokens:
            reasons.append(f"matched {result_kind} claim hints: {', '.join(matched_claim_tokens[:6])}")
        if chronology_hits:
            reasons.append(f"contains chronology cues: {', '.join(chronology_hits[:6])}")

        anchor_sections = [
            section
            for section in classify_anchor_sections(evidence_text)
            if section and section != "general_policy"
        ]
        if anchor_sections:
            score += 1.25 * float(len(anchor_sections))
            reasons.append(f"touches anchor sections: {', '.join(anchor_sections[:4])}")

        if result_kind == "legal":
            url = str(item.get("url") or "")
            domain = _normalize_domain(url)
            citation_text = _clean_text(str(item.get("citation") or ""))
            citation_lower = citation_text.lower()
            authority_source = _clean_text(str(item.get("authority_source") or ""))
            legal_relevance_text = " ".join(
                fragment
                for fragment in (
                    str(item.get("citation") or ""),
                    str(item.get("title") or ""),
                    str(item.get("url") or ""),
                    str(item.get("authority_source") or ""),
                )
                if _clean_text(fragment)
            )
            housing_context = _external_research_has_housing_context(legal_relevance_text)
            procedural_context = _external_research_has_procedural_context(legal_relevance_text)
            strong_procedural_fit = _external_research_has_strong_procedural_fit(legal_relevance_text)
            grievance_process_fit = _external_research_has_grievance_process_fit(evidence_text)
            strong_legal_citation = _external_research_has_strong_legal_citation(legal_relevance_text)
            mismatched_uscode_releasepoint = _is_mismatched_uscode_releasepoint(item)
            federal_register_like = authority_source == "federal_register" or "govinfo.gov" in domain or "federalregister.gov" in domain
            opaque_identifier = _is_opaque_external_research_identifier(citation_text)
            housing_legal_hits = [
                term
                for term in (
                    "fair housing",
                    "public housing",
                    "voucher",
                    "tenant",
                    "grievance",
                    "informal hearing",
                    "hearing",
                    "hud",
                    "982.555",
                    "1437d",
                )
                if term in source_text
            ]
            if citation_text:
                score += 3.0
                reasons.append("has formal citation")
            if authority_source:
                score += 1.5
                reasons.append(f"authority source: {authority_source}")
            if authority_source in {"ecfr", "us_code", "recap", "caselaw", "court_opinion"}:
                score += 5.0
                reasons.append("primary legal source")
            if any(token in source_text for token in ("u.s.c.", "c.f.r.", "hud", "court", "appeal")):
                score += 2.0
            if housing_context:
                score += 1.5
                reasons.append("housing-specific context")
            if procedural_context:
                score += 1.5
                reasons.append("procedural grievance context")
            if grievance_process_fit:
                score += 6.0
                reasons.append("grievance-process authority")
            if domain and any(candidate in domain for candidate in preferred_domains) and not (
                federal_register_like and opaque_identifier and not (housing_context and procedural_context)
            ):
                score += 3.5
                reasons.append(f"preferred housing domain: {domain}")
            if housing_legal_hits:
                score += min(5.0, float(len(housing_legal_hits)) * 1.15)
                reasons.append(f"housing grievance context: {', '.join(housing_legal_hits[:5])}")
            if "c.f.r." in citation_lower or re.search(r"\b\d+\s+cfr\b", citation_lower):
                score += 2.5
                reasons.append("regulatory authority")
            if strong_legal_citation:
                score += 2.5
                reasons.append("strong legal citation")
            if authority_source == "web_fallback" and grievance_process_fit:
                score += 7.5
                reasons.append("promoted grievance-process authority")
            if authority_source == "web_fallback" and not strong_legal_citation:
                score -= 4.5
                reasons.append("promoted web guidance below primary legal authority")
            if mismatched_uscode_releasepoint:
                score -= 14.0
                reasons.append("broad us code releasepoint mismatched to targeted grievance citation")
                blocked = True
            if "u.s.c." in citation_lower and not housing_legal_hits:
                score -= 2.5
                reasons.append("generic statutory citation without housing fit")
            if "34 u.s.c." in citation_lower and not housing_legal_hits:
                score -= 3.0
                reasons.append("generic retaliation statute")
            if "uscode.house.gov" in domain and "prelimusc" in url.lower() and not grievance_process_fit:
                score -= 12.0
                reasons.append("broad us code releasepoint without grievance-process fit")
                blocked = True
            if "retaliation" in source_text and not grievance_process_fit:
                score -= 3.5
                reasons.append("retaliation authority without grievance-process fit")
            if federal_register_like and opaque_identifier and not (housing_context and strong_procedural_fit):
                score -= 10.0
                reasons.append("generic federal register item without grievance-process fit")
                blocked = True
            elif federal_register_like and not strong_legal_citation and not (housing_context and strong_procedural_fit):
                score -= 8.0
                reasons.append("federal register-like item without grievance-process fit")
                blocked = True
            elif federal_register_like and not (housing_context or procedural_context or strong_legal_citation):
                score -= 6.0
                reasons.append("federal register item without complaint-specific fit")
                blocked = True
        else:
            url = str(item.get("url") or "")
            if _is_non_housing_grievance_noise(evidence_text, url=url):
                score -= 8.0
                reasons.append("non-housing grievance noise")
                blocked = True
            complaint_filing_markers = (
                "file a complaint",
                "housing discrimination complaint",
                "/housing-discrimination-complaint",
                "civil rights division",
            )
            if any(marker in source_text or marker in url.lower() for marker in complaint_filing_markers) and not grievance_process_fit:
                score -= 6.0
                reasons.append("complaint-filing page without grievance-process fit")
                blocked = True
            if any(term in source_text for term in _CASE_EVIDENCE_PRIORITY_CUES):
                score += 2.0
                reasons.append("contains evidence-priority cues")
            domain = _normalize_domain(url)
            legal_fallback_domain = bool(
                domain and any(candidate in domain for candidate in _EXTERNAL_RESEARCH_LEGAL_FALLBACK_DOMAINS)
            )
            if domain and any(candidate in domain for candidate in preferred_domains):
                score += 3.5
                reasons.append(f"preferred housing domain: {domain}")
            if domain.endswith(".gov") or domain.endswith(".edu"):
                score += 1.5
                reasons.append(f"trusted domain: {domain}")
            if legal_fallback_domain and strong_legal_citation:
                score += 4.0
                reasons.append("legal fallback domain with strong citation")
            if domain and any(noise_domain in domain for noise_domain in EXTERNAL_RESEARCH_WEB_NOISE_DOMAINS):
                score -= 4.0
                reasons.append(f"generic reference domain: {domain}")
            if any(term in source_text for term in EXTERNAL_RESEARCH_EMPLOYMENT_NOISE_TERMS):
                score -= 3.0
                reasons.append("employment-focused retaliation context")
            if housing_context:
                score += 1.5
                reasons.append("housing-specific context")
            if grievance_process_fit:
                score += 4.5
                reasons.append("grievance-process web support")
            if domain.endswith(".edu") and not housing_context and not (legal_fallback_domain and strong_legal_citation):
                score -= 6.0
                reasons.append("educational grievance page without housing context")
                blocked = True

        scored = dict(item)
        scored["research_priority_score"] = round(score, 3)
        scored["research_priority_reasons"] = _ordered_unique_strings(reasons)
        scored["anchor_sections"] = _ordered_unique_strings(anchor_sections)
        scored["research_relevance_blocked"] = blocked
        return scored

    def _truncate_seed_packet_text(self, text: str, *, max_chars: int = 6000) -> str:
        cleaned = _clean_text(text)
        if len(cleaned) <= max_chars:
            return cleaned
        excerpt = cleaned[: max_chars - 3].rstrip(" ,;:.")
        return f"{excerpt}..."

    def _best_candidate_anchor_text(self, candidate: Dict[str, Any]) -> str:
        for rule in list(candidate.get("matched_rules") or []):
            rule_text = _clean_text(str(rule.get("text") or ""))
            if rule_text:
                return rule_text
        return _clean_text(str(candidate.get("snippet") or ""))

    def _candidate_anchor_sections(self, candidate: Dict[str, Any]) -> List[str]:
        evidence_fragments: List[str] = [
            _clean_text(str(candidate.get("title") or "")),
            _clean_text(str(candidate.get("snippet") or "")),
        ]
        for rule in list(candidate.get("matched_rules") or []):
            evidence_fragments.append(_clean_text(str(rule.get("text") or "")))
            evidence_fragments.append(_clean_text(str(rule.get("section_title") or "")))
        for entity in list(candidate.get("matched_entities") or []):
            evidence_fragments.append(_clean_text(str(entity.get("name") or "")))
            evidence_fragments.append(_clean_text(str(entity.get("type") or "")))

        combined_text = " ".join(fragment for fragment in evidence_fragments if fragment)
        labels = [
            str(label)
            for label in classify_anchor_sections(combined_text)
            if str(label) and str(label) != "general_policy"
        ]

        if labels:
            return labels

        # Fall back to per-fragment classification so a short but precise rule can still surface a label.
        seen: set[str] = set()
        resolved: List[str] = []
        for fragment in evidence_fragments:
            for label in classify_anchor_sections(fragment):
                label_text = str(label)
                if not label_text or label_text == "general_policy" or label_text in seen:
                    continue
                seen.add(label_text)
                resolved.append(label_text)
        return resolved

    def _build_grounding_overview(self, upload_candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        anchor_passages: List[Dict[str, Any]] = []
        seen_titles: set[tuple[str, str]] = set()
        for candidate in upload_candidates:
            anchor_text = self._best_candidate_anchor_text(candidate)
            if not anchor_text:
                continue
            title = str(candidate.get("title") or candidate.get("relative_path") or "Grounding evidence")
            source_path = str(candidate.get("source_path") or "")
            key = (title.lower(), source_path.lower())
            if key in seen_titles:
                continue
            seen_titles.add(key)
            anchor_passages.append(
                {
                    "title": title,
                    "source_path": source_path,
                    "snippet": anchor_text,
                    "section_labels": self._candidate_anchor_sections(candidate),
                }
            )
        anchor_sections: List[str] = []
        seen_sections: set[str] = set()
        for passage in anchor_passages:
            for label in list(passage.get("section_labels") or []):
                label_text = str(label).strip()
                if label_text and label_text not in seen_sections:
                    seen_sections.add(label_text)
                    anchor_sections.append(label_text)
        evidence_summary = " ".join(
            snippet for snippet in [str(item.get("snippet") or "").strip() for item in anchor_passages[:2]] if snippet
        )
        return {
            "evidence_summary": evidence_summary,
            "anchor_passages": anchor_passages,
            "anchor_sections": anchor_sections,
        }

    def _build_grounding_chronology_analysis(
        self,
        upload_candidates: Sequence[Dict[str, Any]],
        *,
        claim_type: str,
        query_text: str,
    ) -> Dict[str, Any]:
        timeline_anchors: List[Dict[str, Any]] = []
        seen_anchor_ids: set[str] = set()
        section_labels: List[str] = []
        seen_sections: set[str] = set()
        for candidate in upload_candidates:
            for label in self._candidate_anchor_sections(candidate):
                if label and label not in seen_sections:
                    seen_sections.add(label)
                    section_labels.append(label)
            title = str(candidate.get("title") or candidate.get("relative_path") or "evidence").strip()
            source_path = str(candidate.get("source_path") or "").strip()
            source_type = str(candidate.get("source_type") or "").strip().lower()
            candidate_texts = [self._best_candidate_anchor_text(candidate)]
            if source_type in {"repository_evidence", "parsed_document"}:
                candidate_texts.append(self._resolve_candidate_upload_text(candidate))
            for text in candidate_texts:
                for anchor in self._extract_timeline_anchors_from_text(
                    text,
                    title=title,
                    source_path=source_path,
                    claim_type=claim_type,
                ):
                    anchor_id = str(anchor.get("fact_id") or "")
                    if not anchor_id or anchor_id in seen_anchor_ids:
                        continue
                    seen_anchor_ids.add(anchor_id)
                    timeline_anchors.append(anchor)

        issue_families = [
            family
            for family in (TIMELINE_ISSUE_FAMILY_BY_SECTION.get(label, "") for label in section_labels)
            if family
        ]
        timeline_consistency_summary = self._build_grounding_timeline_consistency_summary(timeline_anchors)
        temporal_proof_objectives = self._dedupe_preserve_order(
            objective
            for label in section_labels
            for objective in ANCHOR_SECTION_TEMPORAL_PROOF_OBJECTIVES.get(label, ())
        )
        chronology_sensitive = bool(set(section_labels).intersection({"grievance_hearing", "appeal_rights", "adverse_action"}))
        unresolved_temporal_issue_count = 0
        chronology_task_count = 0
        issue_labels = self._dedupe_preserve_order(issue_families or (["timeline_anchors"] if chronology_sensitive else []))
        if chronology_sensitive and len(timeline_anchors) < 2:
            unresolved_temporal_issue_count = max(1, len(issue_labels) or len(temporal_proof_objectives) or 1)
            chronology_task_count = max(1, len(temporal_proof_objectives) or len(issue_labels))
        if timeline_consistency_summary:
            if not bool(timeline_consistency_summary.get("partial_order_ready")):
                unresolved_temporal_issue_count = max(1, unresolved_temporal_issue_count)
            if int(timeline_consistency_summary.get("orphan_anchor_count", 0) or 0) > 0:
                chronology_task_count = max(1, chronology_task_count)
            if int(timeline_consistency_summary.get("non_day_precision_fact_count", 0) or 0) > 0:
                temporal_proof_objectives = self._dedupe_preserve_order(
                    [*temporal_proof_objectives, "pin exact dates for chronology-critical events"]
                )
        temporal_issue_ids = [
            _stable_identifier("timeline-issue", claim_type, query_text, label)
            for label in issue_labels
        ]
        bundle_id = _stable_identifier("temporal-proof-bundle", claim_type, query_text, len(timeline_anchors), len(issue_labels))
        fact_ids = [str(anchor.get("fact_id") or "") for anchor in timeline_anchors if str(anchor.get("fact_id") or "")]
        chronology_summary = self._summarize_chronology_anchors(timeline_anchors)
        return {
            "status": "ready" if not unresolved_temporal_issue_count else "warning",
            "timeline_anchors": timeline_anchors[:12],
            "timeline_anchor_count": len(timeline_anchors),
            "chronology_summary": chronology_summary,
            "timeline_consistency_summary": timeline_consistency_summary,
            "issue_families": issue_labels,
            "chronology_task_count": chronology_task_count,
            "unresolved_temporal_issue_count": unresolved_temporal_issue_count,
            "resolved_temporal_issue_count": 0 if unresolved_temporal_issue_count else len(timeline_anchors),
            "unresolved_temporal_issue_ids": temporal_issue_ids[:unresolved_temporal_issue_count],
            "temporal_issue_ids": temporal_issue_ids,
            "temporal_proof_bundle_ids": [bundle_id],
            "temporal_proof_objectives": temporal_proof_objectives,
            "event_ids": fact_ids,
            "temporal_fact_ids": fact_ids,
            "temporal_relation_ids": [],
        }

    def _extract_timeline_anchors_from_text(
        self,
        text: str,
        *,
        title: str,
        source_path: str,
        claim_type: str,
    ) -> List[Dict[str, Any]]:
        original_text = text
        text = text[:MAX_TIMELINE_EXTRACTION_CHARS]
        shared_anchors = self._extract_shared_timeline_anchors_from_text(
            text,
            title=title,
            source_path=source_path,
            claim_type=claim_type,
        )
        if shared_anchors:
            return shared_anchors
        anchors: List[Dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for sentence in _sentence_split(text):
            if len(anchors) >= 6:
                break
            if self._should_skip_timeline_sentence(sentence):
                continue
            for pattern in _TIMELINE_DATE_PATTERNS:
                for match in pattern.finditer(sentence):
                    normalized_date, granularity = _normalize_timeline_date(match)
                    if not normalized_date:
                        continue
                    anchor_text = _clean_text(match.group(0))
                    dedupe_key = (normalized_date, sentence.lower())
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    anchors.append(
                        {
                            "fact_id": _stable_identifier("fact", title, source_path, claim_type, normalized_date, anchor_text),
                            "anchor_text": anchor_text,
                            "sentence": sentence[:320],
                            "start_date": normalized_date,
                            "granularity": granularity,
                            "title": title,
                            "source_path": source_path,
                            "predicate_family": "timeline_anchor",
                        }
                    )
                    if len(anchors) >= 6:
                        break
                if len(anchors) >= 6:
                    break
        if anchors or len(original_text) <= MAX_TIMELINE_EXTRACTION_CHARS:
            return anchors

        # Large inputs skip the shared parser for performance. If the stricter
        # sentence filter yields nothing, fall back to a single lenient anchor
        # so chronology-aware ranking still sees dated material.
        for pattern in _TIMELINE_DATE_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            normalized_date, granularity = _normalize_timeline_date(match)
            if not normalized_date:
                continue
            anchor_text = _clean_text(match.group(0))
            return [
                {
                    "fact_id": _stable_identifier("fact", title, source_path, claim_type, normalized_date, anchor_text),
                    "anchor_text": anchor_text,
                    "sentence": _clean_text(text[:320]),
                    "start_date": normalized_date,
                    "granularity": granularity,
                    "title": title,
                    "source_path": source_path,
                    "predicate_family": "timeline_anchor",
                }
            ]
        return anchors

    def _extract_shared_timeline_anchors_from_text(
        self,
        text: str,
        *,
        title: str,
        source_path: str,
        claim_type: str,
    ) -> List[Dict[str, Any]]:
        if build_shared_temporal_context is None:
            return []
        if len(text) > MAX_TIMELINE_EXTRACTION_CHARS:
            return []

        anchors: List[Dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for sentence in _sentence_split(text):
            if len(anchors) >= 8:
                break
            if len(sentence) > MAX_SHARED_TEMPORAL_SENTENCE_CHARS:
                continue
            if self._should_skip_timeline_sentence(sentence):
                continue
            temporal_context = build_shared_temporal_context(sentence, fallback_text=sentence)
            if not isinstance(temporal_context, dict):
                continue
            start_date = str(temporal_context.get("start_date") or "").strip()
            end_date = str(temporal_context.get("end_date") or "").strip()
            relative_markers = [
                str(marker).strip()
                for marker in list(temporal_context.get("relative_markers") or [])
                if str(marker).strip()
            ]
            if not start_date and not relative_markers:
                continue
            anchor_text = str(temporal_context.get("matched_text") or temporal_context.get("raw_text") or sentence).strip()
            dedupe_key = (start_date or "", "|".join(relative_markers), sentence.lower())
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            anchors.append(
                {
                    "fact_id": _stable_identifier(
                        "fact",
                        title,
                        source_path,
                        claim_type,
                        start_date or end_date or anchor_text,
                        "|".join(relative_markers),
                    ),
                    "anchor_text": anchor_text[:240],
                    "sentence": sentence[:320],
                    "start_date": start_date,
                    "end_date": end_date,
                    "granularity": str(temporal_context.get("granularity") or "unknown"),
                    "is_approximate": bool(temporal_context.get("is_approximate", False)),
                    "is_range": bool(temporal_context.get("is_range", False)),
                    "relative_markers": relative_markers,
                    "title": title,
                    "source_path": source_path,
                    "predicate_family": "timeline_anchor",
                }
            )
        return anchors

    def _build_grounding_timeline_consistency_summary(
        self,
        timeline_anchors: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if build_timeline_consistency_summary is None:
            return {}
        canonical_facts: List[Dict[str, Any]] = []
        for index, anchor in enumerate(timeline_anchors, start=1):
            anchor_dict = dict(anchor or {})
            fact_id = str(anchor_dict.get("fact_id") or f"grounding_anchor_{index}")
            canonical_facts.append(
                {
                    "fact_id": fact_id,
                    "fact_type": "timeline",
                    "description": str(anchor_dict.get("sentence") or anchor_dict.get("anchor_text") or ""),
                    "temporal_context": {
                        "start_date": str(anchor_dict.get("start_date") or ""),
                        "end_date": str(anchor_dict.get("end_date") or ""),
                        "granularity": str(anchor_dict.get("granularity") or ""),
                        "is_approximate": bool(anchor_dict.get("is_approximate", False)),
                        "is_range": bool(anchor_dict.get("is_range", False)),
                        "relative_markers": list(anchor_dict.get("relative_markers") or []),
                    },
                }
            )
        try:
            return dict(build_timeline_consistency_summary(canonical_facts, list(timeline_anchors or []), []) or {})
        except Exception:
            return {}

    def _should_skip_timeline_sentence(self, sentence: str) -> bool:
        normalized = _clean_text(sentence).lower()
        if not normalized:
            return True
        date_match_count = self._count_timeline_dates_in_text(normalized)
        if date_match_count <= 0:
            return True
        has_case_event_cue = any(cue in normalized for cue in _CASE_TIMELINE_EVENT_CUES)
        has_case_action_cue = any(cue in normalized for cue in _CASE_TIMELINE_ACTION_CUES)
        has_party_cue = any(cue in normalized for cue in _CASE_TIMELINE_PARTY_CUES)
        has_non_case_keyword = any(keyword in normalized for keyword in _NON_CASE_TIMELINE_KEYWORDS)
        if has_non_case_keyword and not has_case_action_cue:
            return True
        if date_match_count >= 3 and not has_case_action_cue:
            return True
        if not has_case_action_cue and not has_party_cue:
            return True
        if ("table of contents" in normalized or "chapter " in normalized) and not has_case_action_cue:
            return True
        if has_case_event_cue and has_party_cue:
            return False
        if has_case_action_cue:
            return False
        if has_party_cue and not has_non_case_keyword and date_match_count <= 2:
            return False
        if "effective:" in normalized or normalized.startswith("effective "):
            return True
        return False

    def _count_timeline_dates_in_text(self, text: str) -> int:
        total = 0
        for pattern in _TIMELINE_DATE_PATTERNS:
            total += sum(1 for _ in pattern.finditer(text))
        return total

    def _build_grounding_signal_bundle(
        self,
        upload_candidates: Sequence[Dict[str, Any]],
        *,
        query_text: str,
        claim_type: str,
        grounding_overview: Dict[str, Any],
        chronology_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        anchor_sections = [str(item) for item in list(grounding_overview.get("anchor_sections") or []) if str(item)]
        blocker_objectives = self._dedupe_preserve_order(
            objective
            for label in anchor_sections
            for objective in ANCHOR_SECTION_BLOCKER_OBJECTIVES.get(label, ())
        )
        extraction_targets = self._dedupe_preserve_order(
            target
            for label in anchor_sections
            for target in ANCHOR_SECTION_EXTRACTION_TARGETS.get(label, ())
        )
        if chronology_analysis.get("timeline_anchor_count") and "timeline_anchors" not in extraction_targets:
            extraction_targets.append("timeline_anchors")
        if not extraction_targets:
            extraction_targets = ["timeline_anchors", "actor_role_mapping", "claim_support_mapping"]
        if "claim_support_mapping" not in extraction_targets:
            extraction_targets.append("claim_support_mapping")
        if chronology_analysis.get("unresolved_temporal_issue_count") and "exact_dates" not in blocker_objectives:
            blocker_objectives.insert(0, "exact_dates")

        timeline_anchor_count = int(chronology_analysis.get("timeline_anchor_count", 0) or 0)
        unresolved_temporal_issue_count = int(chronology_analysis.get("unresolved_temporal_issue_count", 0) or 0)
        chronology_task_count = int(chronology_analysis.get("chronology_task_count", 0) or 0)
        timeline_consistency_summary = dict(chronology_analysis.get("timeline_consistency_summary") or {})
        coverage = 0.82 if upload_candidates else 0.55
        if timeline_anchor_count:
            coverage += 0.12
        if unresolved_temporal_issue_count:
            coverage -= min(0.12, 0.04 * unresolved_temporal_issue_count)
        coverage = max(0.0, min(1.0, coverage))
        phase_status = "ready" if upload_candidates and not unresolved_temporal_issue_count else "warning" if upload_candidates else "blocked"
        blockers: List[str] = []
        unresolved_factual_gaps: List[str] = []
        unresolved_legal_gaps: List[str] = []
        if not upload_candidates:
            blockers.append("uploaded_evidence_missing")
            unresolved_factual_gaps.append("Upload case-specific notices, emails, grievance requests, or other records before drafting.")
        if unresolved_temporal_issue_count:
            blockers.extend(["graph_analysis_not_ready", "document_generation_not_ready"])
            unresolved_factual_gaps.append(
                "Case chronology remains incomplete; uploaded evidence or testimony still needs exact dates, response timing, and event order."
            )
        if timeline_consistency_summary and not bool(timeline_consistency_summary.get("partial_order_ready")):
            blockers.append("chronology_partial_order_not_ready")
            unresolved_factual_gaps.append(
                "Chronology anchors still need ordering cleanup before complaint allegations should rely on them."
            )
        if anchor_sections:
            unresolved_legal_gaps.append(f"Map uploaded evidence into supported policy anchors: {', '.join(anchor_sections)}.")

        summary_lines = [
            f"Repository-grounded evidence summary for '{query_text}': {str(grounding_overview.get('evidence_summary') or '').strip()}".strip(),
        ]
        factual_lines = [
            "Tie each uploaded exhibit to a dated event, the responsible HACC actor, and the specific notice, hearing, appeal, or adverse action it proves.",
        ]
        claim_support_lines = [
            "Use uploaded evidence together with repository policy anchors to support each claim element with a traceable exhibit or passage.",
        ]
        exhibit_lines = [
            "Each uploaded file should become an exhibit candidate with filename, source, date, and supported factual proposition.",
        ]
        if unresolved_temporal_issue_count or chronology_task_count:
            factual_lines.append(
                "Chronology remains open: collect exact dates, hearing or appeal timing, response timing, and adverse-action sequence before final drafting."
            )
            claim_support_lines.append(
                "Do not finalize causation or due-process allegations until chronology anchors are attached to uploaded evidence or testimony."
            )

        support_trace_rows = []
        artifact_support_rows = []
        canonical_fact_ids = [str(item) for item in list(chronology_analysis.get("temporal_fact_ids") or []) if str(item)]
        for passage in [dict(item) for item in list(grounding_overview.get("anchor_passages") or []) if isinstance(item, dict)][:6]:
            row = {
                "title": str(passage.get("title") or "anchor evidence"),
                "source_path": str(passage.get("source_path") or ""),
                "snippet": str(passage.get("snippet") or ""),
                "claim_type": claim_type,
                "objective": blocker_objectives[0] if blocker_objectives else "",
                "canonical_fact_ids": canonical_fact_ids[:4],
                "support_trace": ["anchor_passage"],
                "evidence_type": "policy_document",
            }
            support_trace_rows.append(row)
            artifact_support_rows.append(row)

        claim_support_temporal_handoff = {
            "contract_version": "claim_support_temporal_handoff_v1",
            "claim_type": claim_type,
            "claim_element_id": _stable_identifier("claim-element", claim_type, query_text),
            "chronology_task_count": chronology_task_count,
            "unresolved_temporal_issue_count": unresolved_temporal_issue_count,
            "resolved_temporal_issue_count": int(chronology_analysis.get("resolved_temporal_issue_count", 0) or 0),
            "unresolved_temporal_issue_ids": list(chronology_analysis.get("unresolved_temporal_issue_ids") or []),
            "temporal_issue_ids": list(chronology_analysis.get("temporal_issue_ids") or []),
            "event_ids": list(chronology_analysis.get("event_ids") or []),
            "temporal_fact_ids": list(chronology_analysis.get("temporal_fact_ids") or []),
            "temporal_relation_ids": list(chronology_analysis.get("temporal_relation_ids") or []),
            "temporal_proof_bundle_ids": list(chronology_analysis.get("temporal_proof_bundle_ids") or []),
            "temporal_proof_objectives": list(chronology_analysis.get("temporal_proof_objectives") or []),
            "timeline_anchors": list(chronology_analysis.get("timeline_anchors") or []),
        }
        document_generation_handoff = {
            "summary_of_facts_lines": summary_lines[:8],
            "factual_allegation_lines": factual_lines[:8],
            "claim_support_lines_shared": claim_support_lines[:8],
            "claim_support_lines_by_type": {claim_type: claim_support_lines[:8]},
            "exhibit_description_lines": exhibit_lines[:8],
            "blocker_closing_answers": [],
            "blocker_closing_handoff_lines": factual_lines[:4],
            "unresolved_objectives": blocker_objectives[:8],
            "blocker_items": [],
            "canonical_fact_ids": canonical_fact_ids[:12],
            "support_trace_rows": support_trace_rows[:12],
            "artifact_support_rows": artifact_support_rows[:10],
        }
        graph_completeness_signals = {
            "graph_complete": bool(upload_candidates)
            and (timeline_anchor_count > 0 or unresolved_temporal_issue_count == 0)
            and (not timeline_consistency_summary or bool(timeline_consistency_summary.get("partial_order_ready"))),
            "timeline_anchor_count": timeline_anchor_count,
            "chronology_issue_count": unresolved_temporal_issue_count,
            "chronology_task_count": chronology_task_count,
            "timeline_consistency_summary": timeline_consistency_summary,
            "phase_status": phase_status,
        }
        drafting_readiness = {
            "coverage": coverage,
            "phase_status": phase_status,
            "blockers": self._dedupe_preserve_order(blockers),
            "unresolved_factual_gaps": self._dedupe_preserve_order(unresolved_factual_gaps),
            "unresolved_legal_gaps": self._dedupe_preserve_order(unresolved_legal_gaps),
            "timeline_consistency_summary": timeline_consistency_summary,
            "graph_completeness_signals": graph_completeness_signals,
            "document_generation_signals": {
                "supported_anchor_sections": anchor_sections,
                "support_trace_count": len(support_trace_rows),
                "artifact_support_count": len(artifact_support_rows),
            },
        }
        return {
            "workflow_phase_priorities": list(GROUNDING_WORKFLOW_PHASE_PRIORITIES),
            "blocker_objectives": blocker_objectives,
            "extraction_targets": extraction_targets,
            "claim_support_temporal_handoff": claim_support_temporal_handoff,
            "drafting_readiness": drafting_readiness,
            "document_generation_handoff": document_generation_handoff,
            "graph_completeness_signals": graph_completeness_signals,
        }

    def _dedupe_preserve_order(self, values: Iterable[str]) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    def _graph_facts_to_rule_like_records(self, graph_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        rule_like_records: List[Dict[str, Any]] = []
        for entity in list(graph_payload.get("entities", []) or []):
            entity_type = str(entity.get("type") or entity.get("entity_type") or "")
            if entity_type != "fact":
                continue
            attributes = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
            fact_text = _clean_text(str(attributes.get("text") or entity.get("name") or ""))
            if not fact_text:
                continue
            rule_like_records.append(
                {
                    "text": fact_text,
                    "section_title": str(attributes.get("section_title") or "repository_evidence"),
                    "rule_type": "fact",
                    "modality": "evidence",
                }
            )
        return rule_like_records

    def _load_knowledge_graph_documents(self) -> List[CorpusDocument]:
        documents_dir = self.knowledge_graph_dir / "documents"
        if not documents_dir.exists():
            return []

        documents: List[CorpusDocument] = []
        for json_path in sorted(documents_dir.glob("*.json")):
            payload = _safe_json_load(json_path)
            text = str(payload.get("text") or "")
            document_metadata = payload.get("document") or {}
            title = str(document_metadata.get("title") or self._infer_title(text, fallback=json_path.stem))
            source_path = str(document_metadata.get("source_path") or json_path)
            chronology_metadata = self._build_document_chronology_metadata(
                text,
                title=title,
                source_path=source_path,
                source_type="knowledge_graph",
                rules=list(payload.get("rules", []) or []),
                entities=list(payload.get("entities", []) or []),
            )
            documents.append(
                CorpusDocument(
                    document_id=str(payload.get("source_id") or json_path.stem),
                    title=title,
                    text=text,
                    source_type="knowledge_graph",
                    source_path=source_path,
                    metadata={
                        **(payload.get("metadata") or {}),
                        "provider": payload.get("provider", ""),
                        "status": payload.get("status", ""),
                        **chronology_metadata,
                    },
                    rules=list(payload.get("rules", []) or []),
                    entities=list(payload.get("entities", []) or []),
                    relationships=list(payload.get("relationships", []) or []),
                )
            )
        return documents

    def _extract_graph_payload(self, *, text: str, source_id: str, title: str, source_path: Path) -> Dict[str, Any]:
        if extract_graph_from_text is None:
            return {
                "status": "unavailable",
                "entities": [],
                "relationships": [],
                "error": INTEGRATION_IMPORT_ERROR or "graph extraction unavailable",
            }
        payload = extract_graph_from_text(
            text,
            source_id=source_id,
            metadata={
                "title": title,
                "source_path": str(source_path),
            },
        )
        return payload if isinstance(payload, dict) else {"status": "error", "entities": [], "relationships": []}

    def _infer_title(self, text: str, *, fallback: str) -> str:
        for line in str(text or "").splitlines():
            candidate = _clean_text(line)
            if 4 <= len(candidate) <= 180:
                return candidate
        return _clean_text(fallback) or "Untitled document"

    def _score_document(
        self,
        *,
        query_text: str,
        query_tokens: set[str],
        document: CorpusDocument,
    ) -> tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not query_text:
            return 0.0, [], []

        score = 0.0
        matched_rules: List[Dict[str, Any]] = []
        matched_entities: List[Dict[str, Any]] = []

        if query_text.lower() in document.title_lower:
            score += 12.0
        if query_text.lower() in document.text_lower:
            score += 8.0

        if query_tokens:
            title_overlap = len(query_tokens & document.title_tokens)
            text_overlap = len(query_tokens & document.text_tokens)
            rule_overlap = len(query_tokens & document.rule_tokens)
            entity_overlap = len(query_tokens & document.entity_tokens)

            score += 7.0 * (title_overlap / max(len(query_tokens), 1))
            score += 5.0 * (text_overlap / max(len(query_tokens), 1))
            score += 6.0 * (rule_overlap / max(len(query_tokens), 1))
            score += 4.0 * (entity_overlap / max(len(query_tokens), 1))

        for rule in document.rules:
            rule_text = str(rule.get("text") or "")
            rule_tokens = _semantic_tokens(rule_text)
            overlap = len(query_tokens & rule_tokens) if query_tokens else 0
            if overlap == 0 and query_text.lower() not in rule_text.lower():
                continue
            matched_rules.append(
                {
                    "text": rule_text,
                    "section_title": rule.get("section_title", ""),
                    "rule_type": rule.get("rule_type", ""),
                    "modality": rule.get("modality", ""),
                    "overlap": overlap,
                }
            )
            score += 1.5 + overlap

        for entity in document.entities:
            entity_name = str(entity.get("name") or "")
            entity_tokens = _semantic_tokens(entity_name)
            overlap = len(query_tokens & entity_tokens) if query_tokens else 0
            if overlap == 0 and query_text.lower() not in entity_name.lower():
                continue
            matched_entities.append(
                {
                    "name": entity_name,
                    "type": entity.get("type", entity.get("entity_type", "")),
                    "overlap": overlap,
                }
            )
            score += 0.75 + overlap

        if matched_rules:
            score += min(6.0, float(len(matched_rules)))
        if matched_entities:
            score += min(4.0, float(len(matched_entities)))
        if document.source_type == "knowledge_graph":
            score += 0.5

        chronology_summary = document.metadata.get("chronology_summary") if isinstance(document.metadata, dict) else {}
        chronology_anchor_count = int((chronology_summary or {}).get("timeline_anchor_count", 0) or 0)
        chronology_relative_marker_count = int((chronology_summary or {}).get("relative_marker_count", 0) or 0)
        chronology_query_tokens = {
            "date",
            "dates",
            "timeline",
            "chronology",
            "notice",
            "hearing",
            "review",
            "appeal",
            "response",
            "termination",
            "retaliation",
        }
        chronology_intent_tokens = query_tokens & chronology_query_tokens
        if chronology_anchor_count:
            score += min(4.0, chronology_anchor_count * 0.75)
            if chronology_intent_tokens:
                score += min(16.0, 10.0 + (chronology_anchor_count * 2.5))
        elif chronology_intent_tokens:
            # If the query is explicitly asking for chronology/date evidence,
            # lightly down-rank documents that mention the topic but provide no anchors.
            score -= min(6.0, 2.0 + (len(chronology_intent_tokens) * 0.75))
        if chronology_relative_marker_count:
            score += min(2.0, chronology_relative_marker_count * 0.4)

        matched_rules.sort(key=lambda item: (-int(item.get("overlap", 0)), item.get("text", "")))
        matched_entities.sort(key=lambda item: (-int(item.get("overlap", 0)), item.get("name", "")))
        return score, matched_rules, matched_entities

    def _build_document_chronology_metadata(
        self,
        text: str,
        *,
        title: str,
        source_path: str,
        claim_type: str = "housing_discrimination",
        source_type: str = "repository_evidence",
        rules: Optional[Sequence[Dict[str, Any]]] = None,
        entities: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        chronology_text = self._select_document_chronology_text(
            text,
            source_type=source_type,
            rules=rules,
            entities=entities,
        )
        anchors = self._extract_timeline_anchors_from_text(
            chronology_text,
            title=title,
            source_path=source_path,
            claim_type=claim_type,
        )
        chronology_summary = self._summarize_chronology_anchors(anchors)
        return {
            "chronology_summary": chronology_summary,
            "timeline_anchor_count": int(chronology_summary.get("timeline_anchor_count", 0) or 0),
            "timeline_anchor_preview": list(chronology_summary.get("anchor_preview") or []),
        }

    def _select_document_chronology_text(
        self,
        text: str,
        *,
        source_type: str,
        rules: Optional[Sequence[Dict[str, Any]]] = None,
        entities: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> str:
        normalized_source_type = str(source_type or "").strip().lower()
        if normalized_source_type in {"repository_evidence", "parsed_document"}:
            return text

        fragments: List[str] = []
        for rule in list(rules or [])[:12]:
            rule_text = _clean_text(str(rule.get("text") or ""))
            if rule_text:
                fragments.append(rule_text)
        for entity in list(entities or [])[:12]:
            entity_name = _clean_text(str(entity.get("name") or ""))
            if entity_name:
                fragments.append(entity_name)
        focused_text = " ".join(fragment for fragment in fragments if fragment)
        if focused_text:
            return focused_text[:MAX_TIMELINE_EXTRACTION_CHARS]
        return text[: min(len(text), 1200)]

    def _summarize_chronology_anchors(self, anchors: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        normalized_anchors = [dict(item) for item in list(anchors or []) if isinstance(item, dict)]
        exact_date_count = sum(1 for anchor in normalized_anchors if str(anchor.get("start_date") or "").strip())
        relative_marker_count = sum(
            len([marker for marker in list(anchor.get("relative_markers") or []) if str(marker or "").strip()])
            for anchor in normalized_anchors
        )
        anchor_preview = [
            {
                "fact_id": str(anchor.get("fact_id") or "").strip(),
                "start_date": str(anchor.get("start_date") or "").strip(),
                "anchor_text": str(anchor.get("anchor_text") or "").strip(),
                "relative_markers": [str(item) for item in list(anchor.get("relative_markers") or []) if str(item)],
            }
            for anchor in normalized_anchors[:3]
        ]
        return {
            "timeline_anchor_count": len(normalized_anchors),
            "exact_date_count": exact_date_count,
            "relative_marker_count": relative_marker_count,
            "anchor_preview": anchor_preview,
        }

    def _extract_snippet(
        self,
        query_text: str,
        query_tokens: set[str],
        document: CorpusDocument,
        matched_rules: Sequence[Dict[str, Any]],
    ) -> str:
        if matched_rules:
            return str(matched_rules[0].get("text") or "")[:500]

        sentences = _sentence_split(document.text[:12000])
        query_lower = query_text.lower()
        if query_lower:
            for sentence in sentences:
                if query_lower in sentence.lower():
                    return sentence[:500]

        best_sentence = ""
        best_overlap = -1
        for sentence in sentences[:80]:
            overlap = len(query_tokens & _semantic_tokens(sentence))
            if overlap > best_overlap:
                best_overlap = overlap
                best_sentence = sentence
        return best_sentence[:500]

    def _serialize_document(self, document: CorpusDocument) -> Dict[str, Any]:
        return {
            "document_id": document.document_id,
            "title": document.title,
            "text": document.text,
            "source_type": document.source_type,
            "source_path": document.source_path,
            "metadata": dict(document.metadata),
            "rules": list(document.rules),
            "entities": list(document.entities),
            "relationships": list(document.relationships),
        }

    def _build_vector_documents(self, documents: Sequence[CorpusDocument]) -> List[Dict[str, Any]]:
        vector_documents: List[Dict[str, Any]] = []
        for document in documents:
            for index, chunk in enumerate(self._chunk_text(document.text)):
                vector_documents.append(
                    {
                        "id": f"{document.document_id}:chunk:{index}",
                        "text": chunk,
                        "metadata": {
                            "document_id": document.document_id,
                            "title": document.title,
                            "source_type": document.source_type,
                            "source_path": document.source_path,
                            "chunk_index": index,
                        },
                    }
                )
            for rule in document.rules:
                rule_text = _clean_text(str(rule.get("text") or ""))
                if not rule_text:
                    continue
                vector_documents.append(
                    {
                        "id": f"{document.document_id}:rule:{rule.get('rule_id', len(vector_documents))}",
                        "text": f"{document.title}. {rule_text}",
                        "metadata": {
                            "document_id": document.document_id,
                            "title": document.title,
                            "source_type": document.source_type,
                            "source_path": document.source_path,
                            "section_title": rule.get("section_title", ""),
                            "rule_type": rule.get("rule_type", ""),
                            "modality": rule.get("modality", ""),
                        },
                    }
                )
        return vector_documents

    def _chunk_text(self, text: str, *, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
        cleaned = _clean_text(text)
        if not cleaned:
            return []
        chunks: List[str] = []
        step = max(1, chunk_size - overlap)
        start = 0
        while start < len(cleaned):
            chunks.append(cleaned[start : start + chunk_size])
            start += step
        return chunks

    def _source_counts(self, documents: Iterable[CorpusDocument]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for document in documents:
            counts[document.source_type] = counts.get(document.source_type, 0) + 1
        return counts

    def _integration_status(self) -> Dict[str, Any]:
        capability_report = self._shared_capability_report()
        return {
            "complaint_generator_root": str(COMPLAINT_GENERATOR_ROOT),
            "adapter_available": INTEGRATION_IMPORT_ERROR is None,
            "degraded_reason": INTEGRATION_IMPORT_ERROR,
            "preferred_vector_indexes": self._resolve_vector_indexes(index_name="hacc_corpus", index_dir=None),
            "capability_report": capability_report,
            "capabilities": {
                "discovery_available": search_multi_engine_web is not None or search_brave_web is not None,
                "seeded_commoncrawl_available": discover_seeded_commoncrawl is not None,
                "legal_discovery_available": bool(LEGAL_SCRAPERS_AVAILABLE),
                "scrape_available": scrape_web_content is not None,
                "graph_available": extract_graph_from_text is not None,
                "documents_available": bool(DOCUMENTS_AVAILABLE),
                "vector_available": bool(VECTOR_STORE_AVAILABLE),
                "embeddings_available": bool(EMBEDDINGS_AVAILABLE),
                "documents_degraded_reason": str(DOCUMENTS_ERROR) if (not DOCUMENTS_AVAILABLE and DOCUMENTS_ERROR is not None) else None,
                "vector_degraded_reason": str(VECTOR_STORE_ERROR) if (not VECTOR_STORE_AVAILABLE and VECTOR_STORE_ERROR is not None) else None,
                "legal_degraded_reason": str(LEGAL_SCRAPERS_ERROR) if (not LEGAL_SCRAPERS_AVAILABLE and LEGAL_SCRAPERS_ERROR is not None) else None,
            },
        }

    def _shared_capability_report(self) -> Dict[str, Any]:
        if summarize_ipfs_datasets_capability_report is None:
            return {
                "status": "degraded",
                "available_count": 0,
                "degraded_count": 0,
                "available_capabilities": [],
                "degraded_capabilities": {},
                "error": INTEGRATION_IMPORT_ERROR or "capability report unavailable",
            }
        try:
            payload = summarize_ipfs_datasets_capability_report()
        except Exception as exc:
            return {
                "status": "error",
                "available_count": 0,
                "degraded_count": 0,
                "available_capabilities": [],
                "degraded_capabilities": {},
                "error": str(exc),
            }
        if isinstance(payload, dict):
            return payload
        return {
            "status": "error",
            "available_count": 0,
            "degraded_count": 0,
            "available_capabilities": [],
            "degraded_capabilities": {},
            "error": "Unexpected capability report payload",
        }

    def _normalize_domain_filters(self, domain_filter: Optional[Sequence[str] | str]) -> set[str]:
        if domain_filter is None:
            return set()
        if isinstance(domain_filter, str):
            values = [domain_filter]
        else:
            values = list(domain_filter)
        return {value.lower().strip() for value in values if value and value.strip()}

    def _matches_domain_filter(self, item: Dict[str, Any], normalized_filters: set[str]) -> bool:
        if not normalized_filters:
            return True
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        domain = str(metadata.get("domain") or _normalize_domain(str(item.get("url") or ""))).lower()
        return any(candidate in domain for candidate in normalized_filters)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HACC research and search engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_index = subparsers.add_parser("build-index", help="Build a searchable HACC corpus summary index")
    build_index.add_argument(
        "--output",
        default=str(REPO_ROOT / "research_results/search_indexes/hacc_corpus.summary.json"),
        help="Path to write the index summary JSON",
    )

    build_vector_index = subparsers.add_parser("build-vector-index", help="Build a vector index for the HACC corpus")
    build_vector_index.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "research_results/search_indexes"),
        help="Directory where vector index artifacts should be written",
    )
    build_vector_index.add_argument("--index-name", default="hacc_corpus", help="Vector index name")
    build_vector_index.add_argument("--batch-size", type=int, default=32, help="Embedding batch size")

    search = subparsers.add_parser("search", help="Search the local HACC corpus")
    search.add_argument("query", help="Search query")
    search.add_argument("--top-k", type=int, default=10, help="Maximum number of local results")
    search.add_argument(
        "--source-type",
        action="append",
        default=[],
        help="Optional source type filter (repeatable): parsed_document or knowledge_graph",
    )
    search.add_argument(
        "--search-mode",
        choices=["auto", "lexical", "hybrid", "vector", "package"],
        default="package",
        help="Search strategy. 'package' uses complaint-generator/ipfs_datasets search first and falls back to lexical search.",
    )
    search.add_argument("--use-vector", action="store_true", help="Blend lexical and vector search")
    search.add_argument("--index-dir", default=str(REPO_ROOT / "research_results/search_indexes"), help="Vector index directory")
    search.add_argument("--index-name", default="hacc_corpus", help="Vector index name")

    vector_search = subparsers.add_parser("vector-search", help="Search the local HACC vector index")
    vector_search.add_argument("query", help="Search query")
    vector_search.add_argument("--top-k", type=int, default=10, help="Maximum number of vector results")
    vector_search.add_argument("--index-dir", default=str(REPO_ROOT / "research_results/search_indexes"), help="Vector index directory")
    vector_search.add_argument("--index-name", default="hacc_corpus", help="Vector index name")

    discover = subparsers.add_parser("discover", help="Run web discovery through the ipfs_datasets adapter")
    discover.add_argument("query", help="Discovery query")
    discover.add_argument("--max-results", type=int, default=10, help="Maximum number of results")
    discover.add_argument("--engine", action="append", default=[], help="Preferred search engine (repeatable)")
    discover.add_argument("--domain", action="append", default=[], help="Domain substring filter (repeatable)")
    discover.add_argument("--scrape", action="store_true", help="Scrape the top few discovered URLs")

    seeded_commoncrawl = subparsers.add_parser("seeded-commoncrawl", help="Run shared seeded Common Crawl discovery")
    seeded_commoncrawl.add_argument("--queries-file", required=True, help="Path to a seeded-query text file")
    seeded_commoncrawl.add_argument("--cc-limit", type=int, default=1000, help="Maximum Common Crawl rows per site")
    seeded_commoncrawl.add_argument("--top-per-site", type=int, default=50, help="Top scored URLs to keep per site")
    seeded_commoncrawl.add_argument("--fetch-top", type=int, default=0, help="Fetch and preview the top N URLs per site")
    seeded_commoncrawl.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between site queries")

    discover_legal = subparsers.add_parser("discover-legal", help="Search shared legal authority sources")
    discover_legal.add_argument("query", help="Legal discovery query")
    discover_legal.add_argument("--max-results", type=int, default=10, help="Maximum number of legal results")
    discover_legal.add_argument("--title", help="Optional U.S. Code title filter")
    discover_legal.add_argument("--court", help="Optional RECAP court filter")
    discover_legal.add_argument("--start-date", help="Optional Federal Register start date (YYYY-MM-DD)")
    discover_legal.add_argument("--end-date", help="Optional Federal Register end date (YYYY-MM-DD)")

    research = subparsers.add_parser("research", help="Run local search plus web discovery")
    research.add_argument("query", help="Research query")
    research.add_argument("--top-k", type=int, default=10, help="Maximum number of local results")
    research.add_argument("--max-results", type=int, default=10, help="Maximum number of web results")
    research.add_argument(
        "--search-mode",
        choices=["auto", "lexical", "hybrid", "vector", "package"],
        default="package",
        help="Local search strategy. 'package' uses complaint-generator/ipfs_datasets search first and falls back to lexical search.",
    )
    research.add_argument("--engine", action="append", default=[], help="Preferred search engine (repeatable)")
    research.add_argument("--domain", action="append", default=[], help="Domain substring filter (repeatable)")
    research.add_argument("--scrape", action="store_true", help="Scrape the top few discovered URLs")
    research.add_argument("--use-vector", action="store_true", help="Blend lexical and vector search for local results")
    research.add_argument("--no-legal", action="store_true", help="Disable shared legal authority discovery")
    research.add_argument("--legal-max-results", type=int, default=10, help="Maximum number of legal authority results")
    research.add_argument("--index-dir", default=str(REPO_ROOT / "research_results/search_indexes"), help="Vector index directory")
    research.add_argument("--index-name", default="hacc_corpus", help="Vector index name")

    grounding = subparsers.add_parser(
        "grounding-bundle",
        help="Build repository-grounded evidence candidates and synthetic upload prompts",
    )
    grounding.add_argument("query", help="Grounding query")
    grounding.add_argument("--top-k", type=int, default=5, help="Maximum number of upload candidates")
    grounding.add_argument(
        "--claim-type",
        default="housing_discrimination",
        help="Claim type to reflect in generated prompts",
    )
    grounding.add_argument(
        "--search-mode",
        choices=["auto", "lexical", "hybrid", "vector", "package"],
        default="package",
        help="Search strategy used to build the grounding bundle",
    )
    grounding.add_argument("--use-vector", action="store_true", help="Blend lexical and vector search when supported")

    simulate_upload = subparsers.add_parser(
        "simulate-upload",
        help="Upload repository evidence into the complaint-generator mediator and summarize evaluation",
    )
    simulate_upload.add_argument("query", help="Grounding query")
    simulate_upload.add_argument("--top-k", type=int, default=5, help="Maximum number of upload candidates")
    simulate_upload.add_argument(
        "--claim-type",
        default="housing_discrimination",
        help="Claim type to assign to uploaded evidence",
    )
    simulate_upload.add_argument("--user-id", default="hacc-grounding", help="Mediator user id for the simulated upload")
    simulate_upload.add_argument(
        "--search-mode",
        choices=["auto", "lexical", "hybrid", "vector", "package"],
        default="package",
        help="Search strategy used to choose upload candidates",
    )
    simulate_upload.add_argument("--use-vector", action="store_true", help="Blend lexical and vector search when supported")
    simulate_upload.add_argument("--db-dir", default=None, help="Optional directory for mediator DuckDB artifacts")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    engine = HACCResearchEngine()

    if args.command == "build-index":
        payload = engine.build_index(output_path=args.output)
    elif args.command == "build-vector-index":
        payload = engine.build_vector_index(
            output_dir=args.output_dir,
            index_name=args.index_name,
            batch_size=args.batch_size,
        )
    elif args.command == "search":
        if args.use_vector:
            payload = engine.hybrid_search(
                args.query,
                top_k=args.top_k,
                index_name=args.index_name,
                index_dir=args.index_dir,
                source_types=args.source_type or None,
            )
        else:
            payload = engine.search(
                args.query,
                top_k=args.top_k,
                search_mode=args.search_mode,
                use_vector=args.use_vector,
                index_name=args.index_name,
                index_dir=args.index_dir,
                source_types=args.source_type or None,
            )
    elif args.command == "vector-search":
        payload = engine.search_vector(
            args.query,
            top_k=args.top_k,
            index_name=args.index_name,
            index_dir=args.index_dir,
        )
    elif args.command == "discover":
        payload = engine.discover(
            args.query,
            max_results=args.max_results,
            engines=args.engine or None,
            domain_filter=args.domain or None,
            scrape=args.scrape,
        )
    elif args.command == "seeded-commoncrawl":
        payload = engine.discover_seeded_commoncrawl(
            args.queries_file,
            cc_limit=args.cc_limit,
            top_per_site=args.top_per_site,
            fetch_top=args.fetch_top,
            sleep_seconds=args.sleep_seconds,
        )
    elif args.command == "discover-legal":
        payload = engine.discover_legal_authorities(
            args.query,
            max_results=args.max_results,
            title=args.title,
            court=args.court,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    elif args.command == "grounding-bundle":
        payload = engine.build_grounding_bundle(
            args.query,
            top_k=args.top_k,
            claim_type=args.claim_type,
            search_mode=args.search_mode,
            use_vector=args.use_vector,
        )
    elif args.command == "simulate-upload":
        payload = engine.simulate_evidence_upload(
            args.query,
            top_k=args.top_k,
            claim_type=args.claim_type,
            user_id=args.user_id,
            search_mode=args.search_mode,
            use_vector=args.use_vector,
            db_dir=args.db_dir,
        )
    else:
        payload = engine.research(
            args.query,
            local_top_k=args.top_k,
            web_max_results=args.max_results,
            use_vector=args.use_vector,
            search_mode=args.search_mode,
            vector_index_name=args.index_name,
            vector_index_dir=args.index_dir,
            engines=args.engine or None,
            domain_filter=args.domain or None,
            scrape=args.scrape,
            include_legal=not args.no_legal,
            legal_max_results=args.legal_max_results,
        )

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
