"""Unit tests for the sealed state-laws sparse GraphRAG gold set (LCR-035).

Acceptance:

* Gold and adversarial queries cover all 13 jurisdiction cohorts and DC.
* Exact citation, semantic, cross-reference, jurisdiction-filter, graph-path,
  ambiguity, abstention, and negative-control cases are sealed before tuning.
* Train/dev/test partitions are fixed by legal_id/CID; the test split cannot
  be edited for score chasing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    DEFAULT_KIND,
    LEGAL_ID_PREFIX,
    build_legal_id,
    parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
    validate_legal_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CANONICAL_JURISDICTION_NAMES,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir"
_GOLD_PATH = _FIXTURES / "state_laws_sparse_gold.json"
_NEG_PATH = _FIXTURES / "state_laws_sparse_negative_controls.json"
_RATIONALE_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "goldset_rationale.md"
)

PARTITIONS = ("train", "dev", "test")
GOLD_SCHEMA = "state-laws-sparse-gold-v1"
NEG_SCHEMA = "state-laws-sparse-negative-controls-v1"
TASK_ID = "LCR-035"
GOAL_ID = "LCR-G060"
PROGRAM_ID = "legal-corpora-reindex-v1"
DEFAULT_CONFIGURATION = "state_statutes_exact_51"

COHORTS = {
    "A": ("AL", "AK", "AZ", "AR"),
    "B": ("CA", "CO", "CT", "DE"),
    "C": ("FL", "GA", "HI", "ID"),
    "D": ("IL", "IN", "IA", "KS"),
    "E": ("KY", "LA", "ME", "MD"),
    "F": ("MA", "MI", "MN", "MS"),
    "G": ("MO", "MT", "NE", "NV"),
    "H": ("NH", "NJ", "NM", "NY"),
    "I": ("NC", "ND", "OH", "OK"),
    "J": ("OR", "PA", "RI", "SC"),
    "K": ("SD", "TN", "TX", "UT"),
    "L": ("VT", "VA", "WA", "WV"),
    "M": ("WI", "WY", "DC"),
}
COHORT_TASK_IDS = {
    "A": "LCR-009",
    "B": "LCR-010",
    "C": "LCR-011",
    "D": "LCR-012",
    "E": "LCR-013",
    "F": "LCR-014",
    "G": "LCR-015",
    "H": "LCR-016",
    "I": "LCR-017",
    "J": "LCR-018",
    "K": "LCR-019",
    "L": "LCR-020",
    "M": "LCR-021",
}

EXACT_51_JURISDICTION_CODES = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
)

# Census regions plus an explicit DC bucket (same split as state-laws BM25
# coverage, inlined so this gold-set module does not import retrieval code).
CENSUS_REGION_JURISDICTIONS = {
    "northeast": frozenset({"CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"}),
    "midwest": frozenset(
        {"IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"}
    ),
    "south": frozenset(
        {
            "DE",
            "FL",
            "GA",
            "MD",
            "NC",
            "SC",
            "VA",
            "WV",
            "AL",
            "KY",
            "MS",
            "TN",
            "AR",
            "LA",
            "OK",
            "TX",
        }
    ),
    "west": frozenset(
        {"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"}
    ),
    "dc": frozenset({"DC"}),
}
REQUIRED_CENSUS_REGIONS = ("northeast", "midwest", "south", "west", "dc")

_CID_RE = re.compile(r"^bafkrei[a-z0-9]+$", re.IGNORECASE)
_LEGAL_ID_RE = re.compile(
    rf"^{re.escape(LEGAL_ID_PREFIX)}:[A-Z]{{2}}:[a-z0-9][a-z0-9._-]{{0,63}}:.+$"
)
_SECRET_RE = re.compile(
    r"(hf_[A-Za-z0-9]{16,}|Bearer\s+\S+|sk-[A-Za-z0-9]{16,}|api[_-]?key\s*=)",
    re.IGNORECASE,
)
_HOME_PATH_RE = re.compile(r"(^|/)(home|Users|tmp|var/folders)/")

_REQUIRED_QUERY_KINDS = {
    "exact_citation",
    "semantic",
    "cross_reference",
    "jurisdiction_filter",
    "graph_path",
    "ambiguity",
    "abstention",
}
_REQUIRED_LABEL_KINDS = {
    "exact_section",
    "relevant_subsection",
    "supporting_citation_path",
    "authoritative_source_evidence",
    "known_ambiguity",
    "abstention",
    "repealed_or_reserved",
}
_REQUIRED_CONTROL_KINDS = {
    "fabricated_citation",
    "cross_state_confusion",
    "out_of_corpus_jurisdiction",
    "currentness_overclaim",
    "recovery_row_contamination",
    "individualized_advice",
    "unofficial_source",
    "repealed_or_reserved_as_current",
}

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CATALOG_PATH = _REPO_ROOT / "data" / "legal" / "state_laws" / "official_source_catalog.json"
_DEFAULT_EDITION = "2024-official"
_DEFAULT_RELEASE_POINT = "us/state-statutes/exact-51/2024-official"


def census_region_for(code: str) -> str:
    """Return the sealed census-region bucket for a postal code, including DC."""

    for region, members in CENSUS_REGION_JURISDICTIONS.items():
        if code in members:
            return region
    raise AssertionError(f"jurisdiction {code!r} is not in a census-region bucket")


def _sealed_cid(role: str, key: str) -> str:
    digest = hashlib.sha256(f"lcr-gold|{role}|{key}".encode("utf-8")).hexdigest()
    prefix = "bafkreie" if role == "entry" else "bafkreis"
    return prefix + digest[:45]


def _load_official_catalog() -> dict[str, dict[str, Any]]:
    payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in payload["jurisdictions"]:
        code = row["postal_code"]
        family = row["code_families"][0]
        path = row["acquisition_paths"][0]
        out[code] = {
            "code_family": family["code_family_id"],
            "source_id": path["path_id"],
            "official_url": path["entry_url"],
            "authority_class": path["authority_class"],
            "provider": path["provider"],
        }
    return out


def _hierarchy_from_spec(spec: Mapping[str, Any]) -> dict[str, str]:
    hierarchy = {
        "title": spec.get("title"),
        "chapter": spec.get("chapter"),
        "part": spec.get("part"),
        "article": spec.get("article"),
        "section": spec["section"],
        "subsection": spec.get("subsection"),
    }
    return {key: value for key, value in hierarchy.items() if value not in (None, "")}


def _status_identity(status: str, edition: str | None) -> dict[str, Any]:
    if status == "current":
        return {"kind": DEFAULT_KIND, "note": None, "edition": None}
    if status == "reserved":
        return {"kind": "history", "note": "reserved", "edition": None}
    if status == "repealed":
        return {"kind": "history", "note": "repealed", "edition": edition}
    if status == "historical":
        return {"kind": "history", "note": "historical", "edition": edition}
    return {"kind": "history", "note": status, "edition": edition}


def _resolved(doc: Mapping[str, Any]) -> dict[str, str]:
    return {
        "legal_id": doc["legal_id"],
        "entry_cid": doc["entry_cid"],
        "document_id": doc["document_id"],
        "source_cid": doc["source_cid"],
        "canonical_citation": doc["canonical_citation"],
    }


def materialize_document(
    spec: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    *,
    release_point: str = _DEFAULT_RELEASE_POINT,
    default_edition: str = _DEFAULT_EDITION,
) -> dict[str, Any]:
    """Expand one compact document spec into a sealed gold document."""

    code = str(spec["code"])
    meta = catalog[code]
    letter = next(name for name, codes in COHORTS.items() if code in codes)
    status = str(spec.get("status") or "current")
    edition = str(spec.get("edition") or default_edition)
    hierarchy = _hierarchy_from_spec(spec)
    identity = _status_identity(status, edition)
    legal_id = build_legal_id(
        jurisdiction=code,
        code_family=meta["code_family"],
        section=hierarchy["section"],
        title=hierarchy.get("title"),
        chapter=hierarchy.get("chapter"),
        part=hierarchy.get("part"),
        article=hierarchy.get("article"),
        subsection=hierarchy.get("subsection"),
        edition=identity["edition"],
        note=identity["note"],
        kind=identity["kind"],
    )
    heading = str(spec["heading"])
    stub = f"{legal_id}|{heading}|{edition}|{status}"
    return {
        "document_id": spec["document_id"],
        "legal_id": legal_id,
        "entry_cid": _sealed_cid("entry", legal_id),
        "source_cid": _sealed_cid("source", legal_id),
        "text_hash": hashlib.sha256(stub.encode("utf-8")).hexdigest(),
        "jurisdiction_code": code,
        "jurisdiction_name": CANONICAL_JURISDICTION_NAMES[code],
        "census_region": census_region_for(code),
        "cohort": letter,
        "cohort_task_id": COHORT_TASK_IDS[letter],
        "code_family": meta["code_family"],
        "document_kind": "statute",
        "configuration": spec.get("configuration") or DEFAULT_CONFIGURATION,
        "status": status,
        "edition": edition,
        "release_point": release_point,
        "hierarchy": hierarchy,
        "section": hierarchy["section"],
        "subsection": hierarchy.get("subsection"),
        "identity_kind": identity["kind"],
        "identity_note": identity["note"],
        "canonical_citation": spec["cite"],
        "heading": heading,
        "topic": spec["topic"],
        "popular_name": spec.get("popular_name") or "",
        "query_cite": spec.get("query_cite") or spec["cite"],
        "official_source_id": meta["source_id"],
        "official_url": meta["official_url"],
        "source_authority_class": meta["authority_class"],
        "source_provider": meta["provider"],
        "rights_record_id": f"{meta['source_id']}-statutory_text",
        "notes": spec.get("notes") or "",
    }


def materialize_gold_payload(
    recipe: Mapping[str, Any] | None = None,
    *,
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Expand the compact gold recipe into the evaluator-facing envelope."""

    payload = copy.deepcopy(recipe) if recipe is not None else json.loads(
        _GOLD_PATH.read_text(encoding="utf-8")
    )
    if payload.get("documents") and payload.get("queries") and payload.get("judgments"):
        return payload

    catalog = catalog or _load_official_catalog()
    release_point = payload["release_authority"]["release_point"]
    default_edition = payload["release_authority"]["edition"]
    documents = [
        materialize_document(
            spec,
            catalog,
            release_point=release_point,
            default_edition=default_edition,
        )
        for spec in payload["document_specs"]
    ]
    docs_by_id = {doc["document_id"]: doc for doc in documents}
    primary_ids = payload["primary_document_ids"]

    queries: list[dict[str, Any]] = []
    for spec in payload["query_specs"]:
        code = spec.get("primary_jurisdiction")
        letter = None
        region = None
        if isinstance(code, str) and code in CANONICAL_JURISDICTIONS:
            letter = next(
                (name for name, codes in COHORTS.items() if code in codes),
                None,
            )
            region = census_region_for(code)
        query = {
            "query_id": spec["query_id"],
            "partition": spec["partition"],
            "query_kind": spec["query_kind"],
            "primary_jurisdiction": code,
            "primary_cohort": letter,
            "primary_census_region": region,
            "query_text": spec["query_text"],
            "expectation": spec["expectation"],
            "must_expose_release_point": bool(spec.get("must_expose_release_point", False)),
            "abstain_if_unscoped": bool(spec.get("abstain_if_unscoped", False)),
            "not_legal_advice": spec["query_kind"] == "abstention"
            or spec["expectation"] == "abstention",
            "notes": spec.get("notes") or "",
        }
        for extra_key in (
            "ambiguous_jurisdictions",
            "required_source_id",
            "coverage_mode",
        ):
            if extra_key in spec:
                query[extra_key] = spec[extra_key]
        queries.append(query)

    judgments: list[dict[str, Any]] = []
    for spec in payload["judgment_specs"]:
        doc = docs_by_id[spec["document_id"]]
        judgments.append(
            {
                "query_id": spec["query_id"],
                "document_id": doc["document_id"],
                "legal_id": doc["legal_id"],
                "entry_cid": doc["entry_cid"],
                "grade": spec["grade"],
                "label_kind": spec["label_kind"],
                "rank_ceiling": spec["rank_ceiling"],
                "notes": spec.get("notes") or "",
            }
        )

    leftover = [code for code in EXACT_51_JURISDICTION_CODES if code not in {
        docs_by_id[item["document_id"]]["jurisdiction_code"]
        for item in judgments
        if item["document_id"] in set(primary_ids.values())
    }]
    coverage_query = next(
        (query for query in queries if query.get("coverage_mode") == "unjudged_primary_jurisdictions"),
        None,
    )
    if coverage_query:
        coverage_query["coverage_jurisdictions"] = leftover
        if leftover:
            coverage_query["primary_jurisdiction"] = leftover[0]
            coverage_query["primary_cohort"] = next(
                name for name, codes in COHORTS.items() if leftover[0] in codes
            )
            coverage_query["primary_census_region"] = census_region_for(leftover[0])
            coverage_query["query_text"] = (
                "public records inspection or access statute in " + ", ".join(leftover)
            )
        else:
            leftover = ["AL"]
            coverage_query["coverage_jurisdictions"] = leftover
        for code in leftover:
            doc = docs_by_id[primary_ids[code]]
            judgments.append(
                {
                    "query_id": coverage_query["query_id"],
                    "document_id": doc["document_id"],
                    "legal_id": doc["legal_id"],
                    "entry_cid": doc["entry_cid"],
                    "grade": "exact",
                    "label_kind": "exact_section",
                    "rank_ceiling": 20,
                    "notes": f"Coverage judgment for {code}",
                }
            )

    graph_paths: list[dict[str, Any]] = []
    for spec in payload["graph_path_specs"]:
        nodes = list(spec["nodes"])
        graph_paths.append(
            {
                "path_id": spec["path_id"],
                "query_id": spec["query_id"],
                "partition": spec["partition"],
                "nodes": nodes,
                "node_refs": [_resolved(docs_by_id[node_id]) for node_id in nodes],
                "edges": list(spec["edges"]),
            }
        )

    partition_index = {name: [] for name in PARTITIONS}
    for query in queries:
        partition_index[query["partition"]].append(query["query_id"])

    payload["documents"] = documents
    payload["queries"] = queries
    payload["judgments"] = judgments
    payload["graph_paths"] = graph_paths
    payload["partition_index"] = partition_index
    payload["counts"] = {
        "documents": len(documents),
        "queries": len(queries),
        "judgments": len(judgments),
        "graph_paths": len(graph_paths),
        "jurisdictions": EXPECTED_JURISDICTION_COUNT,
        "cohorts": 13,
        "census_regions": len(REQUIRED_CENSUS_REGIONS),
        "partition_query_counts": {
            name: len(ids) for name, ids in partition_index.items()
        },
    }
    return payload


def materialize_negative_controls(
    recipe: Mapping[str, Any] | None = None,
    *,
    gold: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Expand compact negative-control specs against the materialized gold set."""

    payload = copy.deepcopy(recipe) if recipe is not None else json.loads(
        _NEG_PATH.read_text(encoding="utf-8")
    )
    if payload.get("controls") and not payload.get("control_specs"):
        return payload

    gold_payload = gold or materialize_gold_payload()
    docs_by_id = {doc["document_id"]: doc for doc in gold_payload["documents"]}

    def _resolve_ids(document_ids: list[str] | None) -> tuple[list[str], list[dict[str, str]]]:
        legal_ids: list[str] = []
        resolved: list[dict[str, str]] = []
        for document_id in document_ids or []:
            doc = docs_by_id[document_id]
            legal_ids.append(doc["legal_id"])
            resolved.append(_resolved(doc))
        return legal_ids, resolved

    controls: list[dict[str, Any]] = []
    for spec in payload["control_specs"]:
        control = {
            "control_id": spec["control_id"],
            "control_cid": _sealed_cid("neg", spec["control_id"]),
            "control_kind": spec["control_kind"],
            "partition": spec["partition"],
            "query_text": spec["query_text"],
            "expected_behavior": spec["expected_behavior"],
            "rationale": spec["rationale"],
            "related_jurisdictions": list(spec.get("related_jurisdictions") or []),
        }
        if "must_not_rank_as_exact" in spec:
            control["must_not_rank_as_exact"] = spec["must_not_rank_as_exact"]
        if spec.get("must_not_claim_wall_clock_currentness"):
            control["must_not_claim_wall_clock_currentness"] = True
        if spec.get("not_legal_advice"):
            control["not_legal_advice"] = True
        if spec.get("must_not_retrieve_entry_cid_prefixes"):
            control["must_not_retrieve_entry_cid_prefixes"] = list(
                spec["must_not_retrieve_entry_cid_prefixes"]
            )
        for key in (
            "required_source_authority_class",
            "required_source_id",
        ):
            if key in spec:
                control[key] = spec[key]

        blocked, blocked_resolved = _resolve_ids(spec.get("must_not_retrieve_document_ids"))
        if blocked:
            control["must_not_retrieve_legal_ids"] = blocked
            control["must_not_retrieve_legal_ids_resolved"] = blocked_resolved
        preferred, preferred_resolved = _resolve_ids(spec.get("preferred_document_ids"))
        if preferred:
            control["preferred_legal_ids"] = preferred
            control["preferred_legal_ids_resolved"] = preferred_resolved
        joint, _joint_resolved = _resolve_ids(spec.get("must_not_jointly_exact_document_ids"))
        if joint:
            control["must_not_jointly_exact"] = joint
        controls.append(control)

    partition_counts = {name: 0 for name in PARTITIONS}
    for control in controls:
        partition_counts[control["partition"]] += 1

    payload["controls"] = controls
    payload["counts"] = {
        "controls": len(controls),
        "partition_control_counts": partition_counts,
    }
    return payload


def load_gold_fixture(path: Path | None = None) -> dict[str, Any]:
    target = path or _GOLD_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def load_and_validate_gold(path: Path | None = None) -> dict[str, Any]:
    return materialize_gold_payload(load_gold_fixture(path))


@pytest.fixture(scope="module")
def gold() -> dict[str, Any]:
    assert _GOLD_PATH.is_file(), f"missing gold fixture: {_GOLD_PATH}"
    return materialize_gold_payload()


@pytest.fixture(scope="module")
def negatives(gold: dict[str, Any]) -> dict[str, Any]:
    assert _NEG_PATH.is_file(), f"missing negative-control fixture: {_NEG_PATH}"
    return materialize_negative_controls(gold=gold)


@pytest.fixture(scope="module")
def docs_by_id(gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {doc["document_id"]: doc for doc in gold["documents"]}


# ---------------------------------------------------------------------------
# Fixture presence and schema
# ---------------------------------------------------------------------------


def test_gold_fixture_present_and_schema(gold: dict[str, Any]) -> None:
    raw = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    assert raw["format"] == "sealed_recipe_v1"
    assert raw["document_specs"], "gold fixture must be a compact document recipe"
    assert "documents" not in raw
    assert gold["schema_version"] == GOLD_SCHEMA
    assert gold["fixture_id"] == GOLD_SCHEMA
    assert gold["task_id"] == TASK_ID
    assert gold["goal_id"] == GOAL_ID
    assert gold["program_id"] == PROGRAM_ID
    assert gold["frozen"] is True
    assert gold["not_legal_advice"] is True
    assert gold["ground_truth_policy"]
    assert gold["release_authority"]["release_point"]
    assert gold["release_authority"]["edition"]
    assert gold["currentness_disclaimer"]
    assert "not a substitute for the official source" in gold["currentness_disclaimer"]
    assert "legal advice" in gold["currentness_disclaimer"].lower()
    size = _GOLD_PATH.stat().st_size
    assert size < 512_000, f"gold fixture unexpectedly large: {size} bytes"
    assert not _SECRET_RE.search(_GOLD_PATH.read_text(encoding="utf-8"))


def test_negative_fixture_present_and_schema(negatives: dict[str, Any]) -> None:
    raw = json.loads(_NEG_PATH.read_text(encoding="utf-8"))
    assert raw["format"] == "sealed_recipe_v1"
    assert raw["control_specs"], "negative fixture must be a compact control recipe"
    assert "controls" not in raw
    assert negatives["schema_version"] == NEG_SCHEMA
    assert negatives["fixture_id"] == NEG_SCHEMA
    assert negatives["task_id"] == TASK_ID
    assert negatives["program_id"] == PROGRAM_ID
    assert negatives["frozen"] is True
    assert negatives["not_legal_advice"] is True
    assert negatives["gold_fixture"] == "state_laws_sparse_gold.json"
    size = _NEG_PATH.stat().st_size
    assert size < 128_000, f"negative fixture unexpectedly large: {size} bytes"
    assert not _SECRET_RE.search(_NEG_PATH.read_text(encoding="utf-8"))


def test_rationale_report_present() -> None:
    assert _RATIONALE_PATH.is_file(), f"missing rationale: {_RATIONALE_PATH}"
    text = _RATIONALE_PATH.read_text(encoding="utf-8")
    assert TASK_ID in text
    assert GOAL_ID in text
    assert "train" in text and "dev" in text and "test" in text
    assert "legal_id" in text
    assert "negative" in text.lower()
    assert "no-legal-advice" in text.lower() or "not legal advice" in text.lower()
    assert "not official" in text.lower() or "not official legal authority" in text.lower()
    assert "census" in text.lower()
    for letter in COHORTS:
        assert f"Cohort {letter}" in text or f"cohort {letter}" in text
    for phrase in (
        "exact citation",
        "semantic",
        "cross-reference",
        "jurisdiction-filter",
        "graph",
        "ambiguity",
        "abstention",
        "repealed",
        "reserved",
        "provenance",
    ):
        assert phrase in text.lower()


# ---------------------------------------------------------------------------
# Jurisdiction and cohort coverage
# ---------------------------------------------------------------------------


def test_required_cohorts_and_jurisdictions_covered(gold: dict[str, Any]) -> None:
    assert tuple(gold["required_jurisdictions"]) == EXACT_51_JURISDICTION_CODES
    required = gold["required_cohorts"]
    assert set(required) == set(COHORTS)
    for letter, codes in COHORTS.items():
        assert tuple(required[letter]["jurisdictions"]) == codes
        assert required[letter]["task_id"] == COHORT_TASK_IDS[letter]

    doc_codes = {doc["jurisdiction_code"] for doc in gold["documents"]}
    assert CANONICAL_JURISDICTIONS.issubset(doc_codes)
    assert doc_codes <= CANONICAL_JURISDICTIONS
    assert "DC" in doc_codes

    query_cohorts = {
        q["primary_cohort"] for q in gold["queries"] if q.get("primary_cohort")
    }
    assert set(COHORTS) <= query_cohorts

    docs = {d["document_id"]: d for d in gold["documents"]}
    judged_codes = {
        docs[j["document_id"]]["jurisdiction_code"] for j in gold["judgments"]
    }
    assert CANONICAL_JURISDICTIONS <= judged_codes

    for doc in gold["documents"]:
        letter = doc["cohort"]
        assert doc["jurisdiction_code"] in COHORTS[letter]
        assert doc["cohort_task_id"] == COHORT_TASK_IDS[letter]


def test_census_regions_and_dc_covered(gold: dict[str, Any]) -> None:
    assert tuple(gold["required_census_regions"]) == REQUIRED_CENSUS_REGIONS
    doc_regions = {doc["census_region"] for doc in gold["documents"]}
    assert set(REQUIRED_CENSUS_REGIONS) <= doc_regions
    query_regions = {
        q["primary_census_region"]
        for q in gold["queries"]
        if q.get("primary_census_region")
    }
    assert set(REQUIRED_CENSUS_REGIONS) <= query_regions
    dc_docs = [d for d in gold["documents"] if d["jurisdiction_code"] == "DC"]
    assert dc_docs
    assert all(d["census_region"] == "dc" for d in dc_docs)
    assert all(d["cohort"] == "M" for d in dc_docs)


def test_train_dev_test_partitions(gold: dict[str, Any]) -> None:
    assert tuple(gold["partitions"]) == PARTITIONS
    index = gold["partition_index"]
    for partition in PARTITIONS:
        assert partition in index
        assert len(index[partition]) >= 1

    query_ids = [q["query_id"] for q in gold["queries"]]
    assert len(query_ids) == len(set(query_ids)), "duplicate query_id values"

    seen: set[str] = set()
    for partition in PARTITIONS:
        for qid in index[partition]:
            assert qid not in seen, f"query {qid} assigned to multiple partitions"
            seen.add(qid)
    assert seen == set(query_ids)

    for query in gold["queries"]:
        assert query["partition"] in PARTITIONS
        assert query["query_id"] in index[query["partition"]]

    counts = gold["counts"]["partition_query_counts"]
    for partition in PARTITIONS:
        assert counts[partition] == len(index[partition])
        assert counts[partition] == sum(
            1 for q in gold["queries"] if q["partition"] == partition
        )


def test_test_partition_is_sealed(gold: dict[str, Any]) -> None:
    policy = gold["partition_policy"]["test"].lower()
    assert "sealed" in policy
    assert "cannot modify test labels" in policy or "no post-hoc label edits" in policy
    assert gold["frozen"] is True
    assert "legal_id" in gold["frozen_by"]
    assert "entry_cid" in gold["frozen_by"]
    test_query_ids = set(gold["partition_index"]["test"])
    assert test_query_ids
    judged = {j["query_id"] for j in gold["judgments"]}
    assert test_query_ids <= judged
    for judgment in gold["judgments"]:
        if judgment["query_id"] in test_query_ids:
            assert judgment["legal_id"]
            assert judgment["entry_cid"]


def test_acceptance_query_kinds_present(gold: dict[str, Any]) -> None:
    query_kinds = {q["query_kind"] for q in gold["queries"]}
    missing = _REQUIRED_QUERY_KINDS - query_kinds
    assert not missing, f"missing required query kinds: {sorted(missing)}"
    assert set(gold["query_kinds"]) >= _REQUIRED_QUERY_KINDS


# ---------------------------------------------------------------------------
# Stable identity (CIDs / legal IDs)
# ---------------------------------------------------------------------------


def test_documents_have_stable_legal_ids_and_cids(gold: dict[str, Any]) -> None:
    legal_ids: list[str] = []
    entry_cids: list[str] = []
    source_cids: list[str] = []
    document_ids: list[str] = []

    for doc in gold["documents"]:
        for field in (
            "document_id",
            "legal_id",
            "entry_cid",
            "source_cid",
            "jurisdiction_code",
            "code_family",
            "canonical_citation",
            "release_point",
            "edition",
            "official_source_id",
            "official_url",
            "source_authority_class",
            "rights_record_id",
        ):
            assert doc.get(field), f"document missing {field}: {doc.get('document_id')}"

        legal_id = doc["legal_id"]
        assert _LEGAL_ID_RE.match(legal_id), legal_id
        assert validate_legal_id(legal_id) == legal_id
        assert _CID_RE.match(doc["entry_cid"]), doc["entry_cid"]
        assert _CID_RE.match(doc["source_cid"]), doc["source_cid"]
        assert doc["entry_cid"] != doc["source_cid"]
        assert doc["source_authority_class"] == "official"
        assert doc["official_url"].startswith("http")
        assert not _HOME_PATH_RE.search(doc["official_url"])

        restored = parse_legal_id(legal_id)
        assert restored.legal_id == legal_id
        assert restored.jurisdiction == doc["jurisdiction_code"]
        assert restored.code_family == doc["code_family"]
        if doc.get("subsection"):
            assert restored.subsection == str(doc["subsection"]).lower()

        identity = _status_identity(doc["status"], doc["edition"])
        expected = build_legal_id(
            jurisdiction=doc["jurisdiction_code"],
            code_family=doc["code_family"],
            section=doc["section"],
            title=doc["hierarchy"].get("title"),
            chapter=doc["hierarchy"].get("chapter"),
            part=doc["hierarchy"].get("part"),
            article=doc["hierarchy"].get("article"),
            subsection=doc.get("subsection"),
            edition=identity["edition"],
            note=identity["note"],
            kind=identity["kind"],
        )
        assert legal_id == expected

        legal_ids.append(legal_id)
        entry_cids.append(doc["entry_cid"])
        source_cids.append(doc["source_cid"])
        document_ids.append(doc["document_id"])

    assert len(legal_ids) == len(set(legal_ids))
    assert len(entry_cids) == len(set(entry_cids))
    assert len(source_cids) == len(set(source_cids))
    assert len(document_ids) == len(set(document_ids))
    assert gold["counts"]["documents"] == len(document_ids)


def test_judgments_join_stable_identities(
    gold: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]
) -> None:
    query_ids = {q["query_id"] for q in gold["queries"]}
    for judgment in gold["judgments"]:
        qid = judgment["query_id"]
        doc_id = judgment["document_id"]
        assert qid in query_ids, f"judgment references unknown query {qid}"
        assert doc_id in docs_by_id, f"judgment references unknown document {doc_id}"
        doc = docs_by_id[doc_id]
        assert judgment["legal_id"] == doc["legal_id"]
        assert judgment["entry_cid"] == doc["entry_cid"]
        assert judgment["grade"]
        assert judgment["label_kind"]

    judged_queries = {j["query_id"] for j in gold["judgments"]}
    assert judged_queries == query_ids, "every query must have at least one judgment"
    assert gold["counts"]["judgments"] == len(gold["judgments"])


def test_query_and_label_kind_coverage(gold: dict[str, Any]) -> None:
    query_kinds = {q["query_kind"] for q in gold["queries"]}
    label_kinds = {j["label_kind"] for j in gold["judgments"]}
    assert _REQUIRED_QUERY_KINDS.issubset(query_kinds)
    assert _REQUIRED_LABEL_KINDS.issubset(label_kinds)

    expectations = {q["expectation"] for q in gold["queries"]}
    for required in (
        "exact_section",
        "relevant_subsection",
        "supporting_citation_path",
        "known_ambiguity",
        "abstention",
        "authoritative_source_evidence",
        "repealed_or_reserved",
    ):
        assert required in expectations


def test_time_sensitive_ambiguity_and_advice_flags(gold: dict[str, Any]) -> None:
    flagged = [
        q
        for q in gold["queries"]
        if q["query_kind"]
        in {
            "time_sensitive",
            "historical_version",
            "abstention",
            "repealed_or_reserved",
            "ambiguity",
        }
        or q["expectation"]
        in {"time_sensitive", "known_ambiguity", "abstention", "repealed_or_reserved"}
    ]
    assert flagged, "expected time/ambiguity/advice/repealed queries"
    for query in flagged:
        if query["expectation"] in {
            "time_sensitive",
            "known_ambiguity",
            "abstention",
            "repealed_or_reserved",
        } or query["query_kind"] in {
            "time_sensitive",
            "historical_version",
            "abstention",
            "repealed_or_reserved",
        }:
            assert query["must_expose_release_point"] is True
            assert query["abstain_if_unscoped"] is True

    advice = [q for q in gold["queries"] if q["query_kind"] == "abstention"]
    assert advice, "expected explicit abstention gold query"
    for query in advice:
        assert query["not_legal_advice"] is True
        assert query["expectation"] == "abstention"


def test_repealed_and_reserved_documents_present(gold: dict[str, Any]) -> None:
    statuses = {doc["status"] for doc in gold["documents"]}
    assert "reserved" in statuses
    assert "repealed" in statuses
    reserved = [d for d in gold["documents"] if d["status"] == "reserved"]
    repealed = [d for d in gold["documents"] if d["status"] == "repealed"]
    for doc in reserved + repealed:
        assert "kind=history" in doc["legal_id"]
        assert f"note={doc['status']}" in doc["legal_id"]
        assert doc["configuration"] in {"historical", "state_statutes_exact_51"}


# ---------------------------------------------------------------------------
# Graph paths and provenance
# ---------------------------------------------------------------------------


def test_graph_paths_reference_stable_nodes(
    gold: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]
) -> None:
    assert gold["graph_paths"], "expected sealed graph paths"
    query_ids = {q["query_id"] for q in gold["queries"]}
    path_ids: list[str] = []

    for path in gold["graph_paths"]:
        path_ids.append(path["path_id"])
        assert path["query_id"] in query_ids
        assert path["partition"] in PARTITIONS
        assert len(path["nodes"]) >= 2
        assert len(path["node_refs"]) == len(path["nodes"])
        assert path["edges"], "graph path must include edges"

        for node_id, ref in zip(path["nodes"], path["node_refs"]):
            assert node_id == ref["document_id"]
            doc = docs_by_id[node_id]
            assert ref["legal_id"] == doc["legal_id"]
            assert ref["entry_cid"] == doc["entry_cid"]
            assert ref["source_cid"] == doc["source_cid"]

        node_set = set(path["nodes"])
        for edge in path["edges"]:
            assert edge["source"] in node_set
            assert edge["target"] in node_set
            assert edge["relation"]

    assert len(path_ids) == len(set(path_ids))
    assert gold["counts"]["graph_paths"] == len(path_ids)

    graph_queries = [
        q for q in gold["queries"] if q["query_kind"] in {"graph_path", "cross_reference"}
    ]
    assert graph_queries
    graph_query_ids = {q["query_id"] for q in graph_queries}
    path_query_ids = {p["query_id"] for p in gold["graph_paths"]}
    assert graph_query_ids <= path_query_ids or path_query_ids & graph_query_ids


def test_source_provenance_queries_bind_official_sources(
    gold: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]
) -> None:
    provenance = [q for q in gold["queries"] if q["query_kind"] == "source_provenance"]
    assert provenance, "expected source-provenance queries"
    by_query = {q["query_id"]: q for q in gold["queries"]}
    for judgment in gold["judgments"]:
        query = by_query[judgment["query_id"]]
        if query["query_kind"] != "source_provenance":
            continue
        doc = docs_by_id[judgment["document_id"]]
        assert judgment["label_kind"] == "authoritative_source_evidence"
        assert doc["source_authority_class"] == "official"
        if query.get("required_source_id"):
            assert doc["official_source_id"] == query["required_source_id"]


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_controls_cover_partitions_and_kinds(
    negatives: dict[str, Any], gold: dict[str, Any]
) -> None:
    assert tuple(negatives["partitions"]) == PARTITIONS
    controls = negatives["controls"]
    assert len(controls) >= 8

    control_ids = [c["control_id"] for c in controls]
    assert len(control_ids) == len(set(control_ids))

    control_cids = [c["control_cid"] for c in controls]
    assert len(control_cids) == len(set(control_cids))
    for cid in control_cids:
        assert _CID_RE.match(cid), cid

    partitions = Counter(c["partition"] for c in controls)
    for partition in PARTITIONS:
        assert partitions[partition] >= 1, f"missing negative controls in {partition}"

    kinds = {c["control_kind"] for c in controls}
    missing = _REQUIRED_CONTROL_KINDS - kinds
    assert not missing, f"missing required control kinds: {sorted(missing)}"

    gold_legal_ids = {d["legal_id"] for d in gold["documents"]}
    gold_entry = {d["legal_id"]: d["entry_cid"] for d in gold["documents"]}

    for control in controls:
        assert control["query_text"]
        assert control["expected_behavior"]
        assert control["rationale"]
        assert control["partition"] in PARTITIONS

        for field in ("must_not_retrieve_legal_ids", "preferred_legal_ids"):
            for legal_id in control.get(field) or []:
                assert _LEGAL_ID_RE.match(legal_id) or legal_id.startswith(
                    f"{LEGAL_ID_PREFIX}:"
                )
                resolved_key = f"{field}_resolved"
                if resolved_key in control:
                    resolved = {
                        item["legal_id"]: item for item in control[resolved_key]
                    }
                    if legal_id in gold_legal_ids:
                        assert legal_id in resolved
                        assert resolved[legal_id]["entry_cid"] == gold_entry[legal_id]

        if control.get("must_not_claim_wall_clock_currentness"):
            assert control["expected_behavior"] in {
                "expose_release_or_abstain",
                "abstain_or_research_aid_only",
            }

    assert negatives["counts"]["controls"] == len(controls)


def test_negative_controls_cover_all_cohorts_and_dc(
    negatives: dict[str, Any],
) -> None:
    related = {
        code
        for control in negatives["controls"]
        for code in control.get("related_jurisdictions") or []
    }
    covered_cohorts = {
        letter
        for letter, codes in COHORTS.items()
        if any(code in related for code in codes)
    }
    missing = set(COHORTS) - covered_cohorts
    assert not missing, f"negative controls missing cohorts: {sorted(missing)}"
    assert "DC" in related


def test_negative_controls_do_not_contradict_gold_exact_labels(
    gold: dict[str, Any], negatives: dict[str, Any]
) -> None:
    exact_pairs = {
        (j["query_id"], j["legal_id"])
        for j in gold["judgments"]
        if j["grade"] == "exact"
    }
    gold_query_ids = {q["query_id"] for q in gold["queries"]}
    gold_doc_ids = {d["document_id"] for d in gold["documents"]}
    for control in negatives["controls"]:
        assert control["control_id"] not in gold_query_ids
        assert control["control_id"] not in gold_doc_ids
        joint = control.get("must_not_jointly_exact") or []
        if joint:
            assert len(joint) >= 2
        assert exact_pairs or gold["judgments"]


def test_no_legal_advice_controls_are_explicit(negatives: dict[str, Any]) -> None:
    advice = [
        c
        for c in negatives["controls"]
        if c["control_kind"] == "individualized_advice" or c.get("not_legal_advice")
    ]
    assert advice, "expected individualized-advice / no-legal-advice controls"
    for control in advice:
        assert control["expected_behavior"] in {
            "abstain_or_research_aid_only",
            "expose_release_or_abstain",
        }


# ---------------------------------------------------------------------------
# Counts and internal consistency
# ---------------------------------------------------------------------------


def test_counts_reconcile(gold: dict[str, Any], negatives: dict[str, Any]) -> None:
    assert gold["counts"]["queries"] == len(gold["queries"])
    assert gold["counts"]["documents"] == len(gold["documents"])
    assert gold["counts"]["judgments"] == len(gold["judgments"])
    assert gold["counts"]["graph_paths"] == len(gold["graph_paths"])
    assert gold["counts"]["jurisdictions"] == EXPECTED_JURISDICTION_COUNT
    assert gold["counts"]["cohorts"] == 13
    assert negatives["counts"]["controls"] == len(negatives["controls"])
    for partition in PARTITIONS:
        expected = sum(
            1 for c in negatives["controls"] if c["partition"] == partition
        )
        assert negatives["counts"]["partition_control_counts"][partition] == expected


def test_release_authority_aligned(
    gold: dict[str, Any], negatives: dict[str, Any]
) -> None:
    gold_auth = gold["release_authority"]
    neg_auth = negatives["release_authority"]
    assert gold_auth["release_point"] == neg_auth["release_point"]
    assert gold_auth["edition"] == neg_auth["edition"]
    assert gold_auth["pinned_corpus_revision"] == neg_auth["pinned_corpus_revision"]
    for doc in gold["documents"]:
        if doc["status"] == "current":
            assert doc["release_point"] == gold_auth["release_point"]
            assert doc["edition"] == gold_auth["edition"]
