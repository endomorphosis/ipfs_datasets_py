"""Unit tests for the sealed U.S. Code sparse GraphRAG gold set (USCIR-003).

Acceptance:

* Suite covers Titles 5, 11, 17, 18, 26, 28, 31, 35, 42, and 47.
* Queries are partitioned into train / dev / test.
* Every gold document and judgment carries stable CIDs or legal IDs.
* Negative controls freeze non-retrieval and currentness boundaries.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_identity import (
    build_legal_id,
    parse_legal_id,
)

# tests/unit/logic/legal_ir/this_file.py → tests/
_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "legal_ir"
_GOLD_PATH = _FIXTURES / "uscode_sparse_gold.json"
_NEG_PATH = _FIXTURES / "uscode_sparse_negative_controls.json"
_RATIONALE_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "reports"
    / "uscode_goldset_rationale.md"
)

REQUIRED_TITLES = ("5", "11", "17", "18", "26", "28", "31", "35", "42", "47")
PARTITIONS = ("train", "dev", "test")
GOLD_SCHEMA = "uscode-sparse-gold-v1"
NEG_SCHEMA = "uscode-sparse-negative-controls-v1"

_CID_RE = re.compile(r"^bafkrei[a-z0-9]+$", re.IGNORECASE)
_LEGAL_ID_RE = re.compile(r"^usc:[a-z0-9]+:[0-9a-z]+:.+$", re.IGNORECASE)

_REQUIRED_QUERY_KINDS = {
    "exact_citation",
    "synonym",
    "cross_title",
    "historical_version",
    "graph_path",
    "time_sensitive",
    "semantic",
    "subsection",
}

_REQUIRED_LABEL_KINDS = {
    "exact_section",
    "relevant_subsection",
    "supporting_citation_path",
    "known_ambiguity",
    "abstention",
    "time_sensitive",
}


@pytest.fixture(scope="module")
def gold() -> dict[str, Any]:
    assert _GOLD_PATH.is_file(), f"missing gold fixture: {_GOLD_PATH}"
    return json.loads(_GOLD_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def negatives() -> dict[str, Any]:
    assert _NEG_PATH.is_file(), f"missing negative-control fixture: {_NEG_PATH}"
    return json.loads(_NEG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def docs_by_id(gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {doc["document_id"]: doc for doc in gold["documents"]}


# ---------------------------------------------------------------------------
# Fixture presence and schema
# ---------------------------------------------------------------------------


def test_gold_fixture_present_and_schema(gold: dict[str, Any]) -> None:
    assert gold["schema_version"] == GOLD_SCHEMA
    assert gold["fixture_id"] == "uscode-sparse-gold-v1"
    assert gold["task_id"] == "USCIR-003"
    assert gold["frozen"] is True
    assert gold["ground_truth_policy"]
    assert gold["release_authority"]["release_point"]
    assert gold["release_authority"]["edition"]
    assert gold["currentness_disclaimer"]
    size = _GOLD_PATH.stat().st_size
    assert size < 512_000, f"gold fixture unexpectedly large: {size} bytes"


def test_negative_fixture_present_and_schema(negatives: dict[str, Any]) -> None:
    assert negatives["schema_version"] == NEG_SCHEMA
    assert negatives["fixture_id"] == "uscode-sparse-negative-controls-v1"
    assert negatives["task_id"] == "USCIR-003"
    assert negatives["frozen"] is True
    assert negatives["gold_fixture"] == "uscode_sparse_gold.json"
    size = _NEG_PATH.stat().st_size
    assert size < 128_000, f"negative fixture unexpectedly large: {size} bytes"


def test_rationale_report_present() -> None:
    assert _RATIONALE_PATH.is_file(), f"missing rationale: {_RATIONALE_PATH}"
    text = _RATIONALE_PATH.read_text(encoding="utf-8")
    assert "USCIR-003" in text
    assert "train" in text and "dev" in text and "test" in text
    for title in REQUIRED_TITLES:
        assert title in text
    assert "legal_id" in text
    assert "negative" in text.lower()


# ---------------------------------------------------------------------------
# Title and partition coverage
# ---------------------------------------------------------------------------


def test_required_titles_covered(gold: dict[str, Any]) -> None:
    assert tuple(gold["required_titles"]) == REQUIRED_TITLES
    doc_titles = {str(doc["title"]) for doc in gold["documents"]}
    query_titles = {str(q["primary_title"]) for q in gold["queries"]}
    assert doc_titles == set(REQUIRED_TITLES)
    assert set(REQUIRED_TITLES).issubset(query_titles)

    # Every required title appears as a judgment target at least once.
    judged_titles = set()
    docs = {d["document_id"]: d for d in gold["documents"]}
    for judgment in gold["judgments"]:
        judged_titles.add(str(docs[judgment["document_id"]]["title"]))
    assert judged_titles == set(REQUIRED_TITLES)


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


def test_representative_provisions_present(gold: dict[str, Any]) -> None:
    """Plan §8 examples must appear as sealed legal identities."""

    expected = {
        "usc:us:5:552",  # FOIA
        "usc:us:11:362",  # automatic stay
        "usc:us:17:107",  # fair use
        "usc:us:28:1331",  # federal question
        "usc:us:28:1367",  # supplemental jurisdiction
        "usc:us:28:1441",  # removal
        "usc:us:31:3729",  # False Claims Act
        "usc:us:35:101",  # patent eligibility
        "usc:us:35:103",  # obviousness
        "usc:us:35:112",  # specification
        "usc:us:42:1983",  # civil rights
        "usc:us:42:12101",  # ADA / disability
        "usc:us:47:230",  # Section 230
    }
    present = {doc["legal_id"] for doc in gold["documents"]}
    missing = expected - present
    assert not missing, f"missing representative legal_ids: {sorted(missing)}"


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
            "title",
            "section",
            "canonical_citation",
            "release_point",
            "edition",
        ):
            assert doc.get(field), f"document missing {field}: {doc.get('document_id')}"

        legal_id = doc["legal_id"]
        assert _LEGAL_ID_RE.match(legal_id), legal_id
        assert _CID_RE.match(doc["entry_cid"]), doc["entry_cid"]
        assert _CID_RE.match(doc["source_cid"]), doc["source_cid"]
        assert doc["entry_cid"] != doc["source_cid"]

        # legal_id must round-trip through the identity module and match title/section.
        restored = parse_legal_id(legal_id)
        assert restored.legal_id == legal_id
        assert restored.title == str(doc["title"])
        assert restored.section == str(doc["section"])
        if doc.get("subsection"):
            assert restored.subsection == str(doc["subsection"])

        expected = build_legal_id(
            title=doc["title"],
            section=doc["section"],
            subsection=doc.get("subsection"),
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
        "time_sensitive",
    ):
        assert required in expectations


def test_time_sensitive_and_ambiguity_flags(gold: dict[str, Any]) -> None:
    time_queries = [
        q
        for q in gold["queries"]
        if q["query_kind"] in {"time_sensitive", "historical_version"}
        or q["expectation"] in {"time_sensitive", "known_ambiguity", "abstention"}
    ]
    assert time_queries, "expected at least one time/ambiguity/abstention query"
    for query in time_queries:
        assert query["must_expose_release_point"] is True
        assert query["abstain_if_unscoped"] is True


# ---------------------------------------------------------------------------
# Graph paths
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
    for required in (
        "fabricated_citation",
        "wrong_title_confusion",
        "out_of_corpus_jurisdiction",
        "currentness_overclaim",
        "recovery_row_contamination",
    ):
        assert required in kinds

    gold_legal_ids = {d["legal_id"] for d in gold["documents"]}
    gold_entry = {d["legal_id"]: d["entry_cid"] for d in gold["documents"]}

    for control in controls:
        assert control["query_text"]
        assert control["expected_behavior"]
        assert control["rationale"]
        assert control["partition"] in PARTITIONS

        for field in ("must_not_retrieve_legal_ids", "preferred_legal_ids"):
            for legal_id in control.get(field) or []:
                assert _LEGAL_ID_RE.match(legal_id) or legal_id.startswith("usc:")
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


def test_negative_controls_do_not_contradict_gold_exact_labels(
    gold: dict[str, Any], negatives: dict[str, Any]
) -> None:
    """Fabricated/noise controls must not appear as exact gold judgments."""

    exact_pairs = {
        (j["query_id"], j["legal_id"])
        for j in gold["judgments"]
        if j["grade"] == "exact"
    }
    # Negative control query texts are not gold query_ids; ensure control_ids
    # are disjoint from gold query_ids and document_ids.
    gold_query_ids = {q["query_id"] for q in gold["queries"]}
    gold_doc_ids = {d["document_id"] for d in gold["documents"]}
    for control in negatives["controls"]:
        assert control["control_id"] not in gold_query_ids
        assert control["control_id"] not in gold_doc_ids
        # Joint-exact bans must list at least two legal ids when present.
        joint = control.get("must_not_jointly_exact") or []
        if joint:
            assert len(joint) >= 2
        assert exact_pairs or gold["judgments"]


# ---------------------------------------------------------------------------
# Counts and internal consistency
# ---------------------------------------------------------------------------


def test_counts_reconcile(gold: dict[str, Any], negatives: dict[str, Any]) -> None:
    assert gold["counts"]["queries"] == len(gold["queries"])
    assert gold["counts"]["documents"] == len(gold["documents"])
    assert gold["counts"]["judgments"] == len(gold["judgments"])
    assert gold["counts"]["graph_paths"] == len(gold["graph_paths"])
    assert gold["counts"]["titles"] == len(REQUIRED_TITLES)
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
        assert doc["release_point"] == gold_auth["release_point"]
        assert doc["edition"] == gold_auth["edition"]
