"""PATLAW-070: reviewed USPTO synthetic/public gold corpus contract.

Validates:

* ``GOLD_CORPUS_MANIFEST.json`` inventories and hashes every gold fixture and
  annotation under ``tests/fixtures/uspto/gold``;
* corpus content is synthetic/approved-public only (no private/privileged);
* requirements, citations, dates, and provenance carry reviewer-labeled truth;
* recall, precision, provenance, and false-negative metric gates are
  machine-readable and complete.

This suite is structural and offline. It does not call USPTO networks or run
OCR/extraction pipelines.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final, Mapping

import pytest

# ---------------------------------------------------------------------------
# Paths and closed constants
# ---------------------------------------------------------------------------

REPO_FIXTURE_ROOT: Final = (
    Path(__file__).resolve().parents[2] / "fixtures" / "uspto"
)
GOLD_ROOT: Final = REPO_FIXTURE_ROOT / "gold"
MANIFEST_PATH: Final = REPO_FIXTURE_ROOT / "GOLD_CORPUS_MANIFEST.json"
METRIC_GATES_PATH: Final = GOLD_ROOT / "metrics" / "metric_gates.json"

MANIFEST_SCHEMA: Final = "uspto.gold-corpus-manifest.v1"
CASE_SCHEMA: Final = "uspto.gold-case-recipe.v1"
ANNOTATION_SCHEMA: Final = "uspto.gold-annotation.v1"
GATES_SCHEMA: Final = "uspto.gold-metric-gates.v1"

TASK_ID: Final = "PATLAW-070"
GOAL_ID: Final = "PATLAW-G080"
CONTRACTS_SCHEMA: Final = "uspto.contracts.v1"

ALLOWED_CLASSIFICATIONS: Final = frozenset({"public_official", "public_user"})
FORBIDDEN_CLASSIFICATIONS: Final = frozenset(
    {
        "confidential_application",
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
        "unknown",
    }
)

ALLOWED_PRIVACY_CLASSES: Final = frozenset(
    {"public_synthetic", "approved_public_official"}
)

REQUIRED_GATE_IDS: Final = frozenset(
    {
        "requirement_recall",
        "citation_recall",
        "evidence_precision",
        "provenance_completeness",
        "false_negative_budget",
    }
)

REQUIRED_GATE_FAMILIES: Final = frozenset(
    {"recall", "precision", "provenance", "false_negative"}
)

REQUIRED_CATEGORIES: Final = frozenset(
    {
        "scanned",
        "rotated",
        "forms",
        "tables",
        "docx_pdf_difference",
        "receipts",
        "wrong_identifiers",
        "amendments",
        "current_claims",
        "rescinded",
        "reissued",
        "delayed_docs",
        "authority_amendment",
        "authority_correction",
        "unknowns",
        "adversarial",
        "requirements",
        "citations",
        "dates",
        "provenance",
    }
)

TRUTH_FIELDS: Final = ("requirements", "citations", "dates", "provenance")

PROVENANCE_REQUIRED_FIELDS: Final = frozenset(
    {
        "artifact_id",
        "source_receipt_id",
        "span_id",
        "page_index",
        "origin",
        "classification",
    }
)

# High-signal secret *values* (assignment / bearer / PAN). Mere inventory of
# forbidden artifact *names* in recipes is allowed and expected.
_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]\s*['\"]?[^'\"\s,]{8,}"),
    re.compile(r"(?i)\bpassword\b\s*[:=]\s*['\"]?[^'\"\s,]{4,}"),
    re.compile(r"(?i)\bmfa[_-]?secret\b\s*[:=]\s*['\"]?\S+"),
    re.compile(r"(?i)\bsession[_-]?cookie\b\s*[:=]\s*['\"]?\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]{12,}=*"),
    re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b"),  # crude PAN
)

_SHA256_PREFIX_RE: Final = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _file_sha256_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _iter_gold_files() -> list[Path]:
    return sorted(p for p in GOLD_ROOT.rglob("*") if p.is_file())


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _walk_classifications(value: Any):
    if isinstance(value, Mapping):
        if "classification" in value:
            yield value["classification"]
        for item in value.values():
            yield from _walk_classifications(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_classifications(item)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), f"missing manifest: {MANIFEST_PATH}"
    data = _load_json(MANIFEST_PATH)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def metric_gates() -> dict[str, Any]:
    assert METRIC_GATES_PATH.is_file(), f"missing metric gates: {METRIC_GATES_PATH}"
    data = _load_json(METRIC_GATES_PATH)
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# Manifest schema and inventory
# ---------------------------------------------------------------------------


def test_manifest_schema_and_identity(manifest: dict[str, Any]) -> None:
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["schema_version"] == 1
    assert manifest["task_id"] == TASK_ID
    assert manifest["goal_id"] == GOAL_ID
    assert manifest["corpus_id"] == "uspto-reviewed-gold-v1"
    assert manifest["digest_algorithm"] == "sha256"
    assert manifest["contracts_schema_version"] == CONTRACTS_SCHEMA
    assert set(manifest["annotation_truth_fields"]) == set(TRUTH_FIELDS)
    assert manifest["integrity"]["every_fixture_and_annotation_hashed"] is True
    assert manifest["integrity"]["every_case_has_annotation"] is True
    assert manifest["integrity"]["manifest_excludes_self"] is True


def test_manifest_classification_policy_forbids_private(manifest: dict[str, Any]) -> None:
    policy = manifest["classification_policy"]
    assert set(policy["allowed_classifications"]) == ALLOWED_CLASSIFICATIONS
    assert FORBIDDEN_CLASSIFICATIONS <= set(policy["forbidden_classifications"])
    assert set(policy["allowed_privacy_classes"]) == ALLOWED_PRIVACY_CLASSES
    assert policy["private_real_applications_in_git"] is False
    assert policy["repository_policy"] == "synthetic_and_approved_public_only"


def test_manifest_lists_required_categories(manifest: dict[str, Any]) -> None:
    declared = set(manifest["required_categories"])
    assert REQUIRED_CATEGORIES <= declared


def test_manifest_hashes_every_gold_file(manifest: dict[str, Any]) -> None:
    files = manifest["files"]
    assert isinstance(files, dict) and files

    actual: dict[str, str] = {}
    for path in _iter_gold_files():
        rel = path.relative_to(REPO_FIXTURE_ROOT).as_posix()
        actual[rel] = _file_sha256_digest(path)

    assert set(files) == set(actual), (
        f"manifest file inventory drift; missing={sorted(set(actual) - set(files))} "
        f"extra={sorted(set(files) - set(actual))}"
    )
    for rel, expected in files.items():
        assert _SHA256_PREFIX_RE.match(expected), rel
        assert expected == actual[rel], f"digest mismatch for {rel}"


def test_manifest_excludes_itself_from_file_digests(manifest: dict[str, Any]) -> None:
    files = manifest["files"]
    assert "GOLD_CORPUS_MANIFEST.json" not in files
    for key in files:
        assert not key.endswith("GOLD_CORPUS_MANIFEST.json")


def test_every_case_has_fixture_and_annotation_entries(manifest: dict[str, Any]) -> None:
    cases = manifest["cases"]
    assert isinstance(cases, list) and len(cases) >= 8

    case_ids = [c["case_id"] for c in cases]
    assert len(case_ids) == len(set(case_ids)), "duplicate case_id in manifest"

    files = manifest["files"]
    for entry in cases:
        case_path = entry["case_path"]
        ann_path = entry["annotation_path"]
        assert case_path in files, case_path
        assert ann_path in files, ann_path
        assert (REPO_FIXTURE_ROOT / case_path).is_file()
        assert (REPO_FIXTURE_ROOT / ann_path).is_file()
        assert entry["case_id"] in case_path
        assert entry["case_id"] in ann_path
        assert entry["privacy_class"] in ALLOWED_PRIVACY_CLASSES
        assert entry["classification"] in ALLOWED_CLASSIFICATIONS


def test_category_coverage_across_cases(manifest: dict[str, Any]) -> None:
    seen: set[str] = set()
    for entry in manifest["cases"]:
        seen.update(entry["categories"])
    missing = REQUIRED_CATEGORIES - seen
    assert not missing, f"gold corpus missing required categories: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Case recipes and annotations
# ---------------------------------------------------------------------------


def test_case_recipes_are_public_and_schema_valid(manifest: dict[str, Any]) -> None:
    for entry in manifest["cases"]:
        case = _load_json(REPO_FIXTURE_ROOT / entry["case_path"])
        assert case["schema"] == CASE_SCHEMA
        assert case["schema_version"] == 1
        assert case["task_id"] == TASK_ID
        assert case["goal_id"] == GOAL_ID
        assert case["case_id"] == entry["case_id"]
        assert case["classification"] in ALLOWED_CLASSIFICATIONS
        assert case["source"]["privacy_class"] in ALLOWED_PRIVACY_CLASSES
        assert case["source"]["kind"] in {
            "synthetic",
            "synthetic_public_style",
            "approved_public",
        }
        assert "license" in case and case["license"].get("spdx")
        assert isinstance(case.get("fixture"), dict)
        assert case["contracts_schema_version"] == CONTRACTS_SCHEMA


def test_annotations_have_reviewer_labeled_truth(manifest: dict[str, Any]) -> None:
    corpus_has_requirements = False
    corpus_has_citations = False
    corpus_has_dates = False
    corpus_has_provenance = False

    for entry in manifest["cases"]:
        ann = _load_json(REPO_FIXTURE_ROOT / entry["annotation_path"])
        assert ann["schema"] == ANNOTATION_SCHEMA
        assert ann["schema_version"] == 1
        assert ann["task_id"] == TASK_ID
        assert ann["goal_id"] == GOAL_ID
        assert ann["case_id"] == entry["case_id"]

        reviewer = ann["reviewer"]
        assert reviewer["labeler_id"]
        assert reviewer["reviewed_at"]
        assert reviewer["review_state"] == "complete"
        assert "model" not in reviewer.get("notes", "").lower() or "not model" in reviewer.get(
            "notes", ""
        ).lower()

        truth = ann["truth"]
        for field in TRUTH_FIELDS:
            assert field in truth, f"{entry['case_id']} missing truth.{field}"
            assert isinstance(truth[field], list)

        # Every case must have provenance truth; requirements/citations/dates
        # are required at corpus level (at least one case each).
        assert truth["provenance"], f"{entry['case_id']} missing provenance truth"
        corpus_has_provenance = True
        if truth["requirements"]:
            corpus_has_requirements = True
        if truth["citations"]:
            corpus_has_citations = True
        if truth["dates"]:
            corpus_has_dates = True

        for req in truth["requirements"]:
            assert req["requirement_id"]
            assert req["source_span_id"]
            assert re.fullmatch(r"[0-9a-f]{64}", req["instruction_text_digest"])
            assert req["classification"] in ALLOWED_CLASSIFICATIONS
            assert isinstance(req["legal_citations"], list)
            assert req["review_state"] == "complete"

        for cite in truth["citations"]:
            assert cite["citation_id"]
            assert cite["text"]
            assert cite["source_span_id"]

        for date in truth["dates"]:
            assert date["deadline_id"]
            assert date["event_basis"]
            assert date["candidate_utc"]
            assert date["classification"] in ALLOWED_CLASSIFICATIONS

        for prov in truth["provenance"]:
            # page_index may be null for metadata-only gaps but key must exist
            assert "page_index" in prov, entry["case_id"]
            missing = (PROVENANCE_REQUIRED_FIELDS - set(prov)) - {"page_index"}
            assert not missing, f"{entry['case_id']} provenance missing {sorted(missing)}"
            assert prov["classification"] in ALLOWED_CLASSIFICATIONS
            assert prov["origin"] in {"native", "ocr", "merged", "metadata", "unknown"}

    assert corpus_has_requirements
    assert corpus_has_citations
    assert corpus_has_dates
    assert corpus_has_provenance


def test_annotation_paths_match_case_ids(manifest: dict[str, Any]) -> None:
    for entry in manifest["cases"]:
        case = _load_json(REPO_FIXTURE_ROOT / entry["case_path"])
        ann = _load_json(REPO_FIXTURE_ROOT / entry["annotation_path"])
        assert case["case_id"] == ann["case_id"] == entry["case_id"]


# ---------------------------------------------------------------------------
# Privacy / no private privileged data
# ---------------------------------------------------------------------------


def test_corpus_contains_no_private_or_privileged_classifications(
    manifest: dict[str, Any],
) -> None:
    for entry in manifest["cases"]:
        for rel in (entry["case_path"], entry["annotation_path"]):
            payload = _load_json(REPO_FIXTURE_ROOT / rel)
            for classification in _walk_classifications(payload):
                assert classification in ALLOWED_CLASSIFICATIONS, (
                    f"{rel} has non-public classification {classification!r}"
                )
                assert classification not in FORBIDDEN_CLASSIFICATIONS


def test_corpus_contains_no_secret_material(manifest: dict[str, Any]) -> None:
    """Scan gold text for credential-like payloads (fail-closed)."""
    for path in _iter_gold_files():
        # Skip README prose that may mention forbidden words as documentation.
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _SECRET_PATTERNS:
            match = pattern.search(text)
            assert match is None, f"{path} matched secret pattern {pattern.pattern}: {match.group(0)!r}"


def test_adversarial_canaries_remain_public_synthetic(manifest: dict[str, Any]) -> None:
    adversarial = [c for c in manifest["cases"] if "adversarial" in c["categories"]]
    assert adversarial, "expected at least one adversarial gold case"
    for entry in adversarial:
        assert entry["classification"] in ALLOWED_CLASSIFICATIONS
        assert entry["privacy_class"] in ALLOWED_PRIVACY_CLASSES
        case = _load_json(REPO_FIXTURE_ROOT / entry["case_path"])
        # Canaries must be explicitly synthetic markers, not real private claims.
        blob = json.dumps(case, sort_keys=True)
        assert "SYNTHETIC" in blob or case["source"]["kind"].startswith("synthetic")


# ---------------------------------------------------------------------------
# Metric gates (machine-readable)
# ---------------------------------------------------------------------------


def test_metric_gates_schema_and_required_families(metric_gates: dict[str, Any]) -> None:
    assert metric_gates["schema"] == GATES_SCHEMA
    assert metric_gates["schema_version"] == 1
    assert metric_gates["task_id"] == TASK_ID
    assert metric_gates["goal_id"] == GOAL_ID
    assert set(metric_gates["required_gate_ids"]) == REQUIRED_GATE_IDS
    assert set(metric_gates["families_required"]) == REQUIRED_GATE_FAMILIES

    gates = metric_gates["gates"]
    assert set(gates) >= REQUIRED_GATE_IDS

    families_seen: set[str] = set()
    for gate_id in REQUIRED_GATE_IDS:
        gate = gates[gate_id]
        assert gate["metric_id"]
        assert gate["family"] in REQUIRED_GATE_FAMILIES
        families_seen.add(gate["family"])
        assert gate["operator"] in {">=", "<=", ">", "<", "=="}
        assert isinstance(gate["threshold"], (int, float))
        assert 0.0 <= float(gate["threshold"]) <= 1.0
        assert gate["fail_closed"] is True
        assert gate["definition"]
        assert gate["numerator"]
        assert gate["denominator"]

    assert families_seen == REQUIRED_GATE_FAMILIES


def test_metric_gates_recall_precision_provenance_and_false_negative(
    metric_gates: dict[str, Any],
) -> None:
    gates = metric_gates["gates"]

    recall = gates["requirement_recall"]
    assert recall["family"] == "recall"
    assert recall["operator"] == ">="
    assert recall["threshold"] >= 0.9

    citation = gates["citation_recall"]
    assert citation["family"] == "recall"
    assert citation["operator"] == ">="
    assert citation["threshold"] >= 0.9

    precision = gates["evidence_precision"]
    assert precision["family"] == "precision"
    assert precision["operator"] == ">="
    assert precision["threshold"] >= 0.85

    provenance = gates["provenance_completeness"]
    assert provenance["family"] == "provenance"
    assert provenance["operator"] == ">="
    assert provenance["threshold"] >= 0.95

    false_negative = gates["false_negative_budget"]
    assert false_negative["family"] == "false_negative"
    assert false_negative["operator"] == "<="
    assert false_negative["threshold"] <= 0.1

    # Complement relationship: FN budget should not exceed 1 - requirement recall.
    assert float(false_negative["threshold"]) <= 1.0 - float(recall["threshold"]) + 1e-9


def test_manifest_points_at_metric_gates_and_hashes_them(manifest: dict[str, Any]) -> None:
    rel = manifest["metric_gates_path"]
    assert rel == "gold/metrics/metric_gates.json"
    assert rel in manifest["files"]
    path = REPO_FIXTURE_ROOT / rel
    assert path.is_file()
    assert manifest["files"][rel] == _file_sha256_digest(path)


def test_metric_gates_provenance_field_list_is_complete(metric_gates: dict[str, Any]) -> None:
    required = set(metric_gates["matching"]["provenance_required_fields"])
    assert PROVENANCE_REQUIRED_FIELDS <= required


# ---------------------------------------------------------------------------
# Cross-links: case fixture receipts vs annotation provenance
# ---------------------------------------------------------------------------


def test_annotation_provenance_references_case_artifacts(manifest: dict[str, Any]) -> None:
    for entry in manifest["cases"]:
        case = _load_json(REPO_FIXTURE_ROOT / entry["case_path"])
        ann = _load_json(REPO_FIXTURE_ROOT / entry["annotation_path"])
        fixture = case["fixture"]

        receipt_ids = {
            r["receipt_id"] for r in fixture.get("source_receipts", []) if "receipt_id" in r
        }
        artifact_ids = {
            a["artifact_id"] for a in fixture.get("artifacts", []) if "artifact_id" in a
        }
        # Delayed-doc style cases may mint a placeholder missing artifact id.
        for prov in ann["truth"]["provenance"]:
            assert prov["source_receipt_id"] in receipt_ids or not receipt_ids, (
                f"{entry['case_id']}: unknown receipt {prov['source_receipt_id']}"
            )
            if artifact_ids and not str(prov["artifact_id"]).startswith("art:missing-"):
                assert prov["artifact_id"] in artifact_ids or prov["item_kind"] in {
                    "citation",
                    "retrieval_gap",
                    "artifact_pair",
                }, f"{entry['case_id']}: unknown artifact {prov['artifact_id']}"


def test_gold_root_layout_exists() -> None:
    assert GOLD_ROOT.is_dir()
    assert (GOLD_ROOT / "cases").is_dir()
    assert (GOLD_ROOT / "annotations").is_dir()
    assert (GOLD_ROOT / "metrics").is_dir()
    assert METRIC_GATES_PATH.is_file()
    assert MANIFEST_PATH.is_file()
    # At least one case and matching annotation on disk
    case_files = list((GOLD_ROOT / "cases").glob("*.json"))
    ann_files = list((GOLD_ROOT / "annotations").glob("*.annotation.json"))
    assert case_files
    assert ann_files
    assert len(case_files) == len(ann_files)
