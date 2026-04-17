"""LLM-driven fuzz harness for the Bluebook citation linker.

This module generates Bluebook-style citations with ``llm_router``, attempts to
resolve them through the canonical linker/Hugging Face dataset layer, and can
optionally promote unresolved citation recoveries into the local canonical
dataset merge path that later gets published back to Hugging Face.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import random
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from ipfs_datasets_py import llm_router
from ipfs_datasets_py.processors.legal_data.citation_extraction import CitationExtractor
from ipfs_datasets_py.processors.legal_data.bluebook_citation_linker import (
    BluebookCitationResolver,
    resolve_bluebook_lookup_result_document,
    _normalize_malformed_citation,
    _IDENTIFIER_FIELDS,
    _OFFICIAL_CITE_FIELDS,
    _PAGE_FIELDS,
    _SECTION_FIELDS,
    _STATE_FIELDS,
    _TITLE_FIELDS,
    _TITLE_NUMBER_FIELDS,
    _URL_FIELDS,
    _VOLUME_FIELDS,
    _first_present,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery import (
    recover_missing_legal_citation_source,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    merge_recovery_manifest_into_canonical_dataset,
)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.IGNORECASE | re.DOTALL)
_STATE_CODE_TO_BLUEBOOK = {
    "AK": "Alaska",
    "AL": "Ala.",
    "AR": "Ark.",
    "AZ": "Ariz.",
    "CA": "Cal.",
    "CO": "Colo.",
    "CT": "Conn.",
    "DC": "D.C.",
    "DE": "Del.",
    "FL": "Fla.",
    "GA": "Ga.",
    "HI": "Haw.",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Ill.",
    "IN": "Ind.",
    "KS": "Kan.",
    "KY": "Ky.",
    "LA": "La.",
    "MA": "Mass.",
    "MD": "Md.",
    "ME": "Me.",
    "MI": "Mich.",
    "MN": "Minn.",
    "MO": "Mo.",
    "MS": "Miss.",
    "MT": "Mont.",
    "NC": "N.C.",
    "ND": "N.D.",
    "NE": "Neb.",
    "NH": "N.H.",
    "NJ": "N.J.",
    "NM": "N.M.",
    "NV": "Nev.",
    "NY": "N.Y.",
    "OH": "Ohio",
    "OK": "Okla.",
    "OR": "Or.",
    "PA": "Pa.",
    "RI": "R.I.",
    "SC": "S.C.",
    "SD": "S.D.",
    "TN": "Tenn.",
    "TX": "Tex.",
    "UT": "Utah",
    "VA": "Va.",
    "VT": "Vt.",
    "WA": "Wash.",
    "WI": "Wis.",
    "WV": "W. Va.",
    "WY": "Wyo.",
}


@dataclass
class BluebookCitationCandidate:
    citation_text: str
    context_text: str = ""
    state_code: Optional[str] = None
    corpus_key_hint: Optional[str] = None
    citation_type_hint: Optional[str] = None
    expected_valid: Optional[bool] = None
    notes: Optional[str] = None

    def render_document_text(self) -> str:
        context = str(self.context_text or "").strip()
        if context:
            return context
        return f"The filing cites {self.citation_text} as supporting authority."

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BluebookCitationCandidate":
        return cls(
            citation_text=str(payload.get("citation_text") or "").strip(),
            context_text=str(payload.get("context_text") or "").strip(),
            state_code=(str(payload.get("state_code") or "").strip().upper() or None),
            corpus_key_hint=(str(payload.get("corpus_key_hint") or payload.get("corpus_key") or "").strip() or None),
            citation_type_hint=(str(payload.get("citation_type_hint") or payload.get("citation_type") or "").strip() or None),
            expected_valid=payload.get("expected_valid") if isinstance(payload.get("expected_valid"), bool) else None,
            notes=(str(payload.get("notes") or "").strip() or None),
        )


@dataclass
class BluebookCitationFuzzAttempt:
    ordinal: int
    candidate: BluebookCitationCandidate
    resolution: Dict[str, Any]
    recoveries: List[Dict[str, Any]] = field(default_factory=list)
    merge_reports: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "candidate": asdict(self.candidate),
            "resolution": dict(self.resolution),
            "recoveries": [dict(item) for item in self.recoveries],
            "merge_reports": [dict(item) for item in self.merge_reports],
        }


@dataclass
class BluebookCitationFuzzRun:
    prompt: str
    raw_generation: str
    candidates: List[BluebookCitationCandidate]
    attempts: List[BluebookCitationFuzzAttempt]
    summary: Dict[str, Any]
    seeded_examples: List[Dict[str, Any]] = field(default_factory=list)
    output_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "raw_generation": self.raw_generation,
            "candidates": [asdict(item) for item in self.candidates],
            "attempts": [item.to_dict() for item in self.attempts],
            "summary": dict(self.summary),
            "seeded_examples": [dict(item) for item in self.seeded_examples],
            "output_path": self.output_path,
        }


def build_bluebook_fuzz_generation_prompt(
    *,
    sample_count: int,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    adversarial_ratio: float = 0.35,
    seeded_examples: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    requested_corpora = ", ".join(str(item) for item in (corpus_keys or []) if str(item).strip()) or "usc, cfr, federal_register, public_law, state_statute, case"
    requested_states = ", ".join(str(item).upper() for item in (state_codes or []) if str(item).strip()) or "MN, OR, NY, CA, TX"
    ratio = max(0.0, min(1.0, float(adversarial_ratio)))
    prompt = (
        "Generate synthetic Bluebook-style legal citation fuzz cases for a citation linker.\n"
        f"Return exactly {int(sample_count)} items as JSON only, no markdown, no commentary.\n"
        "Each item must be an object with keys:\n"
        "- citation_text\n"
        "- context_text\n"
        "- state_code\n"
        "- corpus_key_hint\n"
        "- citation_type_hint\n"
        "- expected_valid\n"
        "- notes\n"
        f"Use these target corpora when possible: {requested_corpora}.\n"
        f"Use these state codes when state-specific: {requested_states}.\n"
        f"Make about {ratio:.0%} of the items adversarial or likely-unresolvable edge cases.\n"
        "The remaining items should be plausible real-world legal citations that look resolvable.\n"
        "For context_text, embed the citation naturally inside one short sentence.\n"
        "Keep every object compact and valid JSON.\n"
    )
    examples = [dict(item) for item in list(seeded_examples or []) if isinstance(item, dict)]
    if examples:
        prompt += (
            "Use these real dataset-grounded seed examples as style anchors.\n"
            "Do not copy them verbatim; mutate formats, sections, reporters, or jurisdictions while staying Bluebook-like.\n"
            f"Seed examples JSON:\n{json.dumps(examples, indent=2, sort_keys=True)}\n"
        )
    return prompt


def _first_non_empty_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_non_empty_string(item)
            if text:
                return text
    return str(value).strip()


def _citation_text_from_row(row: Dict[str, Any], fields: Sequence[str]) -> str:
    for field in fields:
        text = _first_non_empty_string(row.get(field))
        if text:
            return text
    return ""


def _citation_text_from_row_text(
    row: Dict[str, Any],
    citation_type: str,
    state_code: Optional[str],
) -> str:
    extractor = CitationExtractor()
    for field in ("text", "head_matter", "name", "name_abbreviation"):
        source_text = _first_non_empty_string(row.get(field))
        if not source_text:
            continue
        for citation in extractor.extract_citations(source_text):
            if citation.type != citation_type:
                continue
            if state_code:
                parsed_state = str(citation.jurisdiction or "").strip().upper()
                if parsed_state not in ("", state_code):
                    continue
            text_value = str(citation.text or "").strip()
            if text_value:
                return text_value
    return ""


def _synthesize_state_statute_citation_from_row(row: Dict[str, Any], state_code: str) -> str:
    source_id = str(row.get("source_id") or "").strip()
    text = _first_non_empty_string(row.get("text"))
    bluebook_abbrev = _STATE_CODE_TO_BLUEBOOK.get(state_code)
    if not bluebook_abbrev:
        return ""

    section_match = None
    for candidate in (source_id, text):
        section_match = re.search(r"(?:Section|Rule|Part)[\s:-]+(?P<section>[A-Za-z0-9.:-]+)", candidate, re.IGNORECASE)
        if section_match:
            break
    if not section_match:
        return ""

    section = str(section_match.group("section") or "").strip().rstrip(".,;:")
    section = re.sub(r"^(?:section|rule|part)[-\\s:]+", "", section, flags=re.IGNORECASE).strip()
    if not section:
        return ""

    lowered_source = source_id.lower()
    if "statute" in lowered_source:
        code_name = "Stat."
    elif "court-rule" in lowered_source or "court rule" in lowered_source:
        code_name = "Court Rules"
    elif "state-admin" in lowered_source or "administrative" in lowered_source:
        code_name = "Admin. Code"
    else:
        return ""
    return f"{bluebook_abbrev} {code_name} § {section}"


def _synthesize_seed_candidate_from_row(
    *,
    corpus_key: str,
    row: Dict[str, Any],
    state_code: Optional[str],
    source_ref: str,
) -> Optional[BluebookCitationCandidate]:
    citation_text = ""
    citation_type = ""
    resolved_state = state_code
    if corpus_key == "us_code":
        title = _first_present(row, _TITLE_NUMBER_FIELDS)
        section = _first_present(row, _SECTION_FIELDS)
        if title not in (None, "") and section not in (None, ""):
            citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS) or f"{title} U.S.C. § {section}"
            citation_type = "usc"
    elif corpus_key == "federal_register":
        volume = _first_present(row, _VOLUME_FIELDS)
        page = _first_present(row, _PAGE_FIELDS)
        if volume not in (None, "") and page not in (None, ""):
            citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS) or f"{volume} FR {page}"
            citation_type = "federal_register"
    elif corpus_key == "caselaw_access_project":
        citation_text = _citation_text_from_row(row, tuple(list(_OFFICIAL_CITE_FIELDS) + ["citations", "name_abbreviation", "name"]))
        if not citation_text:
            citation_text = _citation_text_from_row_text(row, "case", None)
        citation_type = "case"
    elif corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"}:
        resolved_state = str(_first_present(row, _STATE_FIELDS) or state_code or "").strip().upper() or None
        citation_text = _citation_text_from_row(row, tuple(list(_OFFICIAL_CITE_FIELDS) + ["citations"]))
        if not citation_text:
            citation_text = _citation_text_from_row_text(row, "state_statute", resolved_state)
        if not citation_text and resolved_state:
            identifier_fields = [field for field in _IDENTIFIER_FIELDS if field not in {"source_id", "name", "name_abbreviation"}]
            has_structured_fields = any(
                _first_present(row, fields) not in (None, "")
                for fields in (_OFFICIAL_CITE_FIELDS, _SECTION_FIELDS, _TITLE_NUMBER_FIELDS, identifier_fields)
            )
            has_source_backed_fields = bool(_first_non_empty_string(row.get("source_id")) or _first_non_empty_string(row.get("text")))
            if has_structured_fields or has_source_backed_fields:
                citation_text = _synthesize_state_statute_citation_from_row(row, resolved_state)
        citation_type = "state_statute"
    if not citation_text:
        return None

    title = _citation_text_from_row(row, _TITLE_FIELDS)
    url = _citation_text_from_row(row, _URL_FIELDS)
    context = f"The filing relies on {citation_text} as authority."
    note_parts = [f"seeded from {corpus_key}", f"source_ref={source_ref}"]
    if title:
        note_parts.append(f"title={title}")
    if url:
        note_parts.append(f"url={url}")
    return BluebookCitationCandidate(
        citation_text=citation_text,
        context_text=context,
        state_code=resolved_state,
        corpus_key_hint=corpus_key,
        citation_type_hint=citation_type,
        expected_valid=True,
        notes="; ".join(note_parts),
    )


def _normalized_partition_key(corpus_key: str, state_code: Optional[str]) -> str:
    corpus_value = str(corpus_key or "").strip() or "unknown"
    state_value = str(state_code or "").strip().upper() or "federal"
    return f"{corpus_value}:{state_value}"


def _select_evenly_spaced_candidates(
    candidates: Sequence[BluebookCitationCandidate],
    *,
    limit: int,
) -> List[BluebookCitationCandidate]:
    if limit <= 0:
        return []
    values = list(candidates)
    if len(values) <= limit:
        return values
    if limit == 1:
        return [values[0]]

    selected: List[BluebookCitationCandidate] = []
    used_indexes = set()
    last_index = len(values) - 1
    for offset in range(limit):
        raw_index = round((offset * last_index) / (limit - 1))
        index = min(last_index, max(0, int(raw_index)))
        while index in used_indexes and index < last_index:
            index += 1
        while index in used_indexes and index > 0:
            index -= 1
        if index in used_indexes:
            continue
        used_indexes.add(index)
        selected.append(values[index])
    return selected


def _balanced_select_candidates(
    candidates: Sequence[BluebookCitationCandidate],
    *,
    total_limit: int,
    per_partition_limit: Optional[int] = None,
) -> List[BluebookCitationCandidate]:
    values = [item for item in candidates if isinstance(item, BluebookCitationCandidate)]
    if total_limit <= 0 or not values:
        return []

    by_partition: Dict[str, List[BluebookCitationCandidate]] = {}
    partition_order: List[str] = []
    for item in values:
        key = _normalized_partition_key(str(item.corpus_key_hint or ""), item.state_code)
        if key not in by_partition:
            partition_order.append(key)
            by_partition[key] = []
        by_partition[key].append(item)

    working = {
        key: list(_select_evenly_spaced_candidates(group, limit=min(len(group), max(1, int(per_partition_limit or len(group))))))
        for key, group in by_partition.items()
    }

    selected: List[BluebookCitationCandidate] = []
    while len(selected) < total_limit:
        advanced = False
        for key in partition_order:
            group = working.get(key) or []
            if not group:
                continue
            selected.append(group.pop(0))
            advanced = True
            if len(selected) >= total_limit:
                break
        if not advanced:
            break
    return selected


def collect_seeded_bluebook_fuzz_candidates(
    *,
    resolver: BluebookCitationResolver,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    examples_per_corpus: int = 2,
    sample_count: Optional[int] = None,
    max_examples_per_state: Optional[int] = None,
    max_examples_per_source: Optional[int] = None,
    shuffle_seed: int = 0,
) -> List[BluebookCitationCandidate]:
    requested_corpora = [str(item).strip() for item in (corpus_keys or []) if str(item).strip()] or [
        "us_code",
        "federal_register",
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
        "caselaw_access_project",
    ]
    requested_states = [str(item).strip().upper() for item in (state_codes or []) if str(item).strip()] or ["MN", "OR", "NY"]

    max_per_corpus = max(1, int(examples_per_corpus))
    max_per_state = max(1, int(max_examples_per_state or max_per_corpus))
    max_per_source = max(1, int(max_examples_per_source or max_per_state))
    candidates: List[BluebookCitationCandidate] = []
    for corpus_key in requested_corpora:
        state_iter = requested_states if corpus_key.startswith("state_") else [None]
        corpus_candidates: List[BluebookCitationCandidate] = []
        for state_code in state_iter:
            state_candidates: List[BluebookCitationCandidate] = []
            for source_ref in resolver._iter_corpus_sources(corpus_key, state_code=state_code):
                local_source = source_ref
                if str(source_ref).startswith(("http://", "https://")):
                    materialized = resolver._materialize_remote_parquet(source_ref)
                    if not materialized:
                        continue
                    local_source = materialized
                rows = resolver._load_local_parquet_rows(local_source)
                source_candidates: List[BluebookCitationCandidate] = []
                for row in rows:
                    candidate = _synthesize_seed_candidate_from_row(
                        corpus_key=corpus_key,
                        row=dict(row),
                        state_code=state_code,
                        source_ref=source_ref,
                    )
                    if candidate is None:
                        continue
                    if corpus_key.startswith("state_") and state_code:
                        candidate_state = str(candidate.state_code or "").strip().upper()
                        if candidate_state and candidate_state != str(state_code).strip().upper():
                            continue
                    source_candidates.append(candidate)
                state_candidates.extend(_select_evenly_spaced_candidates(source_candidates, limit=max_per_source))
            corpus_candidates.extend(_select_evenly_spaced_candidates(state_candidates, limit=max_per_state))
        candidates.extend(_select_evenly_spaced_candidates(corpus_candidates, limit=max_per_corpus))

    rng = random.Random(int(shuffle_seed))
    ordered_candidates = list(candidates)
    rng.shuffle(ordered_candidates)
    if sample_count is not None:
        ordered_candidates = _balanced_select_candidates(
            ordered_candidates,
            total_limit=max(1, int(sample_count)),
            per_partition_limit=max_examples_per_state,
        )
    return ordered_candidates


def _extract_json_payload(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("LLM generation returned empty text")

    candidates = [text]
    fenced = _JSON_FENCE_RE.findall(text)
    candidates.extend(item.strip() for item in fenced if item.strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            pass
        try:
            parsed, _end = decoder.raw_decode(candidate)
            return parsed
        except Exception:
            pass

    raise ValueError("Unable to parse JSON payload from LLM generation output")


def parse_bluebook_fuzz_candidates(raw_text: str) -> List[BluebookCitationCandidate]:
    payload = _extract_json_payload(raw_text)
    if isinstance(payload, dict):
        for key in ("items", "citations", "results", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
    if not isinstance(payload, list):
        raise ValueError("Expected generated citation payload to be a JSON list")

    candidates: List[BluebookCitationCandidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        candidate = BluebookCitationCandidate.from_dict(item)
        if candidate.citation_text:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("Generated citation payload did not contain any usable citations")
    return candidates


def _attempt_succeeded(attempt: BluebookCitationFuzzAttempt) -> bool:
    return int(attempt.resolution.get("matched_citation_count") or 0) > 0


def _wilson_upper_bound(failures: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = failures / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = phat + z2 / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * total)) / total)
    return min(1.0, (center + margin) / denom)


def _summarize_attempts_by_corpus(
    attempts: Sequence[BluebookCitationFuzzAttempt],
    *,
    max_acceptable_failure_rate: float,
    min_actionable_failures: int,
) -> Dict[str, Any]:
    by_corpus: Dict[str, List[BluebookCitationFuzzAttempt]] = {}
    for attempt in attempts:
        corpus_key = str(attempt.candidate.corpus_key_hint or "unknown").strip() or "unknown"
        by_corpus.setdefault(corpus_key, []).append(attempt)

    summary_rows: List[Dict[str, Any]] = []
    for corpus_key, corpus_attempts in sorted(by_corpus.items()):
        total = len(corpus_attempts)
        failures = sum(1 for item in corpus_attempts if not _attempt_succeeded(item))
        successes = total - failures
        failure_rate = (failures / total) if total else 0.0
        upper_bound = _wilson_upper_bound(failures, total)
        actionable = failures >= max(1, int(min_actionable_failures)) and upper_bound > float(max_acceptable_failure_rate)
        sample_failure_examples = [
            {
                "citation_text": item.candidate.citation_text,
                "state_code": item.candidate.state_code,
                "notes": item.candidate.notes,
            }
            for item in corpus_attempts
            if not _attempt_succeeded(item)
        ][:5]
        summary_rows.append(
            {
                "corpus_key": corpus_key,
                "sample_count": total,
                "success_count": successes,
                "failure_count": failures,
                "failure_rate": failure_rate,
                "estimated_success_rate": (successes / total) if total else 0.0,
                "wilson_upper_bound_95": upper_bound,
                "wilson_lower_bound_success_95": max(0.0, 1.0 - upper_bound),
                "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
                "actionable_failure_cluster": actionable,
                "sample_failure_examples": sample_failure_examples,
            }
        )

    actionable = [row for row in summary_rows if bool(row.get("actionable_failure_cluster"))]
    return {
        "per_corpus": summary_rows,
        "actionable_corpora": [row["corpus_key"] for row in actionable],
        "actionable_corpus_count": len(actionable),
    }


def _cluster_failure_recoveries(attempts: Sequence[BluebookCitationFuzzAttempt]) -> List[Dict[str, Any]]:
    clusters: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for attempt in attempts:
        if _attempt_succeeded(attempt):
            continue
        corpus_key = str(attempt.candidate.corpus_key_hint or "unknown").strip() or "unknown"
        for recovery in attempt.recoveries:
            scraper_patch = dict(recovery.get("scraper_patch") or {})
            host = str(scraper_patch.get("host") or "").strip()
            target_file = str(scraper_patch.get("target_file") or "").strip()
            key = (corpus_key, host, target_file)
            cluster = clusters.setdefault(
                key,
                {
                    "corpus_key": corpus_key,
                    "host": host,
                    "target_file": target_file,
                    "failure_count": 0,
                    "citations": [],
                    "manifest_paths": [],
                    "patch_paths": [],
                },
            )
            cluster["failure_count"] += 1
            citation_text = str(recovery.get("citation_text") or attempt.candidate.citation_text or "").strip()
            if citation_text and citation_text not in cluster["citations"]:
                cluster["citations"].append(citation_text)
            manifest_path = str(recovery.get("manifest_path") or "").strip()
            if manifest_path and manifest_path not in cluster["manifest_paths"]:
                cluster["manifest_paths"].append(manifest_path)
            patch_path = str(scraper_patch.get("patch_path") or "").strip()
            if patch_path and patch_path not in cluster["patch_paths"]:
                cluster["patch_paths"].append(patch_path)

    ordered = sorted(clusters.values(), key=lambda item: (-int(item["failure_count"]), item["corpus_key"], item["host"], item["target_file"]))
    for item in ordered:
        item["citations"] = item["citations"][:10]
        item["manifest_paths"] = item["manifest_paths"][:10]
        item["patch_paths"] = item["patch_paths"][:10]
    return ordered


def _collect_malformed_repairs(
    candidates: Sequence[BluebookCitationCandidate],
) -> List[Dict[str, Any]]:
    repairs: Dict[tuple[str, str], Dict[str, Any]] = {}
    for candidate in candidates:
        raw = str(candidate.citation_text or "").strip()
        normalized = _normalize_malformed_citation(raw)
        if not raw or normalized == raw:
            continue
        key = (raw, normalized)
        entry = repairs.setdefault(
            key,
            {
                "raw_citation": raw,
                "normalized_citation": normalized,
                "count": 0,
                "examples": [],
            },
        )
        entry["count"] += 1
        examples = entry["examples"]
        if len(examples) < 3:
            examples.append(
                {
                    "state_code": candidate.state_code,
                    "corpus_key_hint": candidate.corpus_key_hint,
                    "context_text": candidate.context_text,
                }
            )
    ranked = sorted(repairs.values(), key=lambda item: (-int(item["count"]), item["raw_citation"]))
    return ranked


def _build_failure_backlog(
    *,
    attempts: Sequence[BluebookCitationFuzzAttempt],
    coverage_summary: Dict[str, Any],
    failure_patch_clusters: Sequence[Dict[str, Any]],
    malformed_repairs: Sequence[Dict[str, Any]],
    max_acceptable_failure_rate: float,
    min_actionable_failures: int,
) -> Dict[str, Any]:
    actionable_corpora = {
        str(item).strip()
        for item in list(coverage_summary.get("actionable_corpora") or [])
        if str(item).strip()
    }
    backlog_clusters: List[Dict[str, Any]] = []
    for cluster in failure_patch_clusters:
        corpus_key = str(cluster.get("corpus_key") or "").strip() or "unknown"
        if corpus_key not in actionable_corpora:
            continue
        matching_attempts = [
            attempt
            for attempt in attempts
            if not _attempt_succeeded(attempt)
            and str(attempt.candidate.corpus_key_hint or "unknown").strip() == corpus_key
            and any(
                str((recovery.get("scraper_patch") or {}).get("target_file") or "").strip() == str(cluster.get("target_file") or "").strip()
                and str((recovery.get("scraper_patch") or {}).get("host") or "").strip() == str(cluster.get("host") or "").strip()
                for recovery in attempt.recoveries
            )
        ]
        backlog_clusters.append(
            {
                **dict(cluster),
                "actionable": True,
                "recommended_next_step": "Use recovery candidates and manifest evidence to patch the target scraper, then rerun the seed-only audit for this corpus cluster.",
                "sample_contexts": [
                    {
                        "citation_text": attempt.candidate.citation_text,
                        "context_text": attempt.candidate.context_text,
                        "state_code": attempt.candidate.state_code,
                        "notes": attempt.candidate.notes,
                    }
                    for attempt in matching_attempts[:5]
                ],
            }
        )

    return {
        "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
        "min_actionable_failures": int(min_actionable_failures),
        "actionable_corpora": sorted(actionable_corpora),
        "cluster_count": len(backlog_clusters),
        "clusters": backlog_clusters,
        "malformed_repairs": list(malformed_repairs or [])[:50],
    }


async def run_bluebook_linker_fuzz_harness(
    *,
    sample_count: int = 12,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 1.0,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    adversarial_ratio: float = 0.35,
    allow_hf_fallback: bool = True,
    exhaustive: bool = True,
    enable_recovery: bool = True,
    recovery_max_candidates: int = 8,
    recovery_archive_top_k: int = 3,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    merge_recovered_rows: bool = False,
    seed_from_corpora: bool = False,
    seed_only: bool = False,
    seed_examples_per_corpus: int = 2,
    max_seed_examples_per_state: Optional[int] = None,
    max_seed_examples_per_source: Optional[int] = None,
    sampling_shuffle_seed: int = 0,
    max_acceptable_failure_rate: float = 0.10,
    min_actionable_failures: int = 2,
    output_dir: Optional[str | Path] = None,
    resolver: Optional[BluebookCitationResolver] = None,
    llm_generate_func: Optional[Callable[..., str]] = None,
    resolve_document_func: Optional[Callable[..., Dict[str, Any]]] = None,
    recovery_func: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
    merge_manifest_func: Optional[Callable[..., Dict[str, Any]]] = None,
) -> BluebookCitationFuzzRun:
    active_resolver = resolver or BluebookCitationResolver(allow_hf_fallback=allow_hf_fallback)
    seeded_candidates = collect_seeded_bluebook_fuzz_candidates(
        resolver=active_resolver,
        corpus_keys=corpus_keys,
        state_codes=state_codes,
        examples_per_corpus=seed_examples_per_corpus,
        sample_count=sample_count if (seed_from_corpora or seed_only) else None,
        max_examples_per_state=max_seed_examples_per_state,
        max_examples_per_source=max_seed_examples_per_source,
        shuffle_seed=sampling_shuffle_seed,
    ) if seed_from_corpora else []
    seeded_examples = [asdict(item) for item in seeded_candidates]
    prompt = build_bluebook_fuzz_generation_prompt(
        sample_count=sample_count,
        corpus_keys=corpus_keys,
        state_codes=state_codes,
        adversarial_ratio=adversarial_ratio,
        seeded_examples=seeded_examples,
    )

    if seed_only:
        raw_generation = ""
        candidates = list(seeded_candidates)[: max(1, int(sample_count))]
    else:
        active_generate = llm_generate_func or llm_router.generate_text
        raw_generation = active_generate(
            prompt,
            provider=provider,
            model_name=model_name,
            temperature=temperature,
        )
        candidates = parse_bluebook_fuzz_candidates(raw_generation)[: max(1, int(sample_count))]

    active_resolve_document = resolve_document_func or resolve_bluebook_lookup_result_document
    active_recovery = recovery_func or recover_missing_legal_citation_source
    active_merge = merge_manifest_func or merge_recovery_manifest_into_canonical_dataset

    attempts: List[BluebookCitationFuzzAttempt] = []
    matched_attempts = 0
    unmatched_citations = 0
    recovery_count = 0
    merged_count = 0

    for ordinal, candidate in enumerate(candidates, start=1):
        resolution = active_resolve_document(
            candidate.render_document_text(),
            state_code=candidate.state_code,
            resolver=active_resolver,
            exhaustive=exhaustive,
            include_recovery=False,
            include_suggestions=False,
        )

        if int(resolution.get("matched_citation_count") or 0) > 0:
            matched_attempts += 1
        unmatched_payloads = [dict(item) for item in list(resolution.get("unresolved_citations") or []) if isinstance(item, dict)]
        unmatched_citations += len(unmatched_payloads)

        recoveries: List[Dict[str, Any]] = []
        merge_reports: List[Dict[str, Any]] = []
        if enable_recovery:
            for unresolved in unmatched_payloads:
                metadata = dict(unresolved.get("metadata") or {})
                recovery = await active_recovery(
                    citation_text=str(unresolved.get("citation_text") or ""),
                    normalized_citation=str(unresolved.get("normalized_citation") or unresolved.get("citation_text") or ""),
                    corpus_key=str(metadata.get("recovery_corpus_key") or unresolved.get("corpus_key") or "") or None,
                    state_code=str(metadata.get("state_code") or "") or None,
                    metadata={
                        "candidate_corpora": list(metadata.get("candidate_corpora") or []),
                    },
                    max_candidates=recovery_max_candidates,
                    archive_top_k=recovery_archive_top_k,
                    publish_to_hf=publish_to_hf,
                    hf_token=hf_token,
                )
                recoveries.append(dict(recovery))
                recovery_count += 1

                manifest_path = str(recovery.get("manifest_path") or "").strip()
                if merge_recovered_rows and manifest_path:
                    merge_report = active_merge(manifest_path)
                    merge_reports.append(dict(merge_report))
                    if str(merge_report.get("status") or "").lower() == "success":
                        merged_count += 1

        attempts.append(
            BluebookCitationFuzzAttempt(
                ordinal=ordinal,
                candidate=candidate,
                resolution=dict(resolution),
                recoveries=recoveries,
                merge_reports=merge_reports,
            )
        )

    summary = {
        "sample_count_requested": int(sample_count),
        "sample_count_executed": len(candidates),
        "matched_attempt_count": matched_attempts,
        "matched_attempt_ratio": (matched_attempts / len(candidates)) if candidates else 0.0,
        "unmatched_citation_count": unmatched_citations,
        "recovery_count": recovery_count,
        "merged_recovery_count": merged_count,
        "provider": provider,
        "model_name": model_name,
        "allow_hf_fallback": bool(allow_hf_fallback),
        "exhaustive": bool(exhaustive),
        "publish_to_hf": bool(publish_to_hf),
        "merge_recovered_rows": bool(merge_recovered_rows),
        "seed_from_corpora": bool(seed_from_corpora),
        "seed_only": bool(seed_only),
        "seeded_example_count": len(seeded_examples),
        "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
        "min_actionable_failures": int(min_actionable_failures),
    }
    summary["coverage_by_corpus"] = _summarize_attempts_by_corpus(
        attempts,
        max_acceptable_failure_rate=max_acceptable_failure_rate,
        min_actionable_failures=min_actionable_failures,
    )
    summary["failure_patch_clusters"] = _cluster_failure_recoveries(attempts)
    summary["malformed_repairs"] = _collect_malformed_repairs(candidates)
    summary["sampling"] = {
        "seed_examples_per_corpus": int(seed_examples_per_corpus),
        "max_seed_examples_per_state": int(max_seed_examples_per_state or seed_examples_per_corpus),
        "max_seed_examples_per_source": int(max_seed_examples_per_source or max_seed_examples_per_state or seed_examples_per_corpus),
        "sampling_shuffle_seed": int(sampling_shuffle_seed),
    }
    failure_backlog = _build_failure_backlog(
        attempts=attempts,
        coverage_summary=summary["coverage_by_corpus"],
        failure_patch_clusters=summary["failure_patch_clusters"],
        malformed_repairs=summary["malformed_repairs"],
        max_acceptable_failure_rate=max_acceptable_failure_rate,
        min_actionable_failures=min_actionable_failures,
    )
    summary["failure_patch_backlog"] = failure_backlog

    output_path: Optional[str] = None
    run = BluebookCitationFuzzRun(
        prompt=prompt,
        raw_generation=str(raw_generation),
        candidates=candidates,
        attempts=attempts,
        summary=summary,
        seeded_examples=seeded_examples,
    )
    if output_dir is not None:
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        output_file = output_root / "bluebook_linker_fuzz_run.json"
        output_file.write_text(json.dumps(run.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        backlog_file = output_root / "bluebook_linker_fuzz_patch_backlog.json"
        backlog_file.write_text(json.dumps(failure_backlog, indent=2, sort_keys=True), encoding="utf-8")
        repairs_file = output_root / "bluebook_linker_fuzz_malformed_repairs.json"
        repairs_file.write_text(json.dumps(summary["malformed_repairs"], indent=2, sort_keys=True), encoding="utf-8")
        run.summary["failure_patch_backlog_path"] = str(backlog_file)
        run.summary["malformed_repairs_path"] = str(repairs_file)
        output_path = str(output_file)
        run.output_path = output_path

    return run


__all__ = [
    "BluebookCitationCandidate",
    "BluebookCitationFuzzAttempt",
    "BluebookCitationFuzzRun",
    "build_bluebook_fuzz_generation_prompt",
    "collect_seeded_bluebook_fuzz_candidates",
    "parse_bluebook_fuzz_candidates",
    "run_bluebook_linker_fuzz_harness",
]
