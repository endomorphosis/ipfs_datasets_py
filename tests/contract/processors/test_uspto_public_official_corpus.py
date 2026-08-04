"""PATLAW-139: approved-public-official USPTO evaluation corpus contract.

Validates:

* ``manifest.json`` distinguishes official bytes, annotations, and synthetic
  supplements;
* every artifact carries source URL/CID, public status, rights/privacy review,
  acquisition date, label reviewer/version, and split assignment;
* leakage and duplicate-family checks pass;
* synthetic material is never labeled official; private/privileged classes are
  absent.

This suite is structural and offline. It does not call USPTO networks or
download official packages.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, Iterator, Mapping

import pytest

# ---------------------------------------------------------------------------
# Paths and closed constants
# ---------------------------------------------------------------------------

REPO_FIXTURE_ROOT: Final = (
    Path(__file__).resolve().parents[2] / "fixtures" / "uspto"
)
CORPUS_ROOT: Final = REPO_FIXTURE_ROOT / "gold" / "public_official"
MANIFEST_PATH: Final = CORPUS_ROOT / "manifest.json"
README_PATH: Final = CORPUS_ROOT / "README.md"

MANIFEST_SCHEMA: Final = "uspto.public-official-corpus-manifest.v1"
TASK_ID: Final = "PATLAW-139"
GOAL_ID: Final = "PATLAW-G151"
CORPUS_ID: Final = "uspto-approved-public-official-v1"
CONTRACTS_SCHEMA: Final = "uspto.contracts.v1"

ARTIFACT_ROLES: Final = frozenset(
    {"official_bytes", "annotation", "synthetic_supplement"}
)
ALLOWED_SPLITS: Final = frozenset({"train", "validation", "test", "held_out"})
DEVELOPMENT_SPLITS: Final = frozenset({"train", "validation"})
EVALUATION_SPLITS: Final = frozenset({"test", "held_out"})

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
    {"approved_public_official", "public_synthetic"}
)
ALLOWED_PUBLIC_STATUS: Final = frozenset({"public", "approved_public"})

REQUIRED_LABEL_COVERAGE: Final = frozenset(
    {
        "layout",
        "fields",
        "instructions",
        "citations",
        "obligations",
        "submission_evidence",
        "deadlines",
        "expected_uncertainty",
    }
)
REQUIRED_DOCUMENT_FAMILIES: Final = frozenset(
    {
        "office_action",
        "submission_amendment",
        "filing_receipt",
        "regulation_authority",
        "statute_authority",
        "agency_guidance",
        "forms_tables",
        "deadline_calendar",
    }
)

_ISO_DATE_RE: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_RFC3339_UTC_RE: Final = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)
_SHA256_HEX_RE: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_SOURCE_CID_RE: Final = re.compile(
    r"\A(?:sha256:[0-9a-f]{64}|cid:sha256:[0-9a-f]{64}"
    r"|bafy[a-z2-7]{10,}|bagu[a-z2-7]{10,}|Qm[1-9A-HJ-NP-Za-km-z]{44,})\Z"
)
_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]\s*['\"]?[^'\"\s,]{8,}"),
    re.compile(r"(?i)\bpassword\b\s*[:=]\s*['\"]?[^'\"\s,]{4,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]{12,}=*"),
    re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b"),
)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _iter_artifacts(manifest: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    for case in manifest["cases"]:
        for artifact in case["artifacts"]:
            assert isinstance(artifact, dict)
            yield artifact


def _iter_case_artifacts(
    manifest: Mapping[str, Any],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for case in manifest["cases"]:
        for artifact in case["artifacts"]:
            yield case, artifact


def _has_source_url_or_cid(artifact: Mapping[str, Any]) -> bool:
    url = artifact.get("source_url")
    cid = artifact.get("source_cid")
    has_url = isinstance(url, str) and bool(url.strip())
    has_cid = isinstance(cid, str) and bool(cid.strip())
    return has_url or has_cid


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), f"missing manifest: {MANIFEST_PATH}"
    data = _load_json(MANIFEST_PATH)
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# Layout and identity
# ---------------------------------------------------------------------------


def test_corpus_layout_exists() -> None:
    assert CORPUS_ROOT.is_dir()
    assert MANIFEST_PATH.is_file()
    assert README_PATH.is_file()
    readme = README_PATH.read_text(encoding="utf-8")
    assert "official_bytes" in readme
    assert "annotation" in readme
    assert "synthetic_supplement" in readme
    assert "PATLAW-139" in readme


def test_manifest_schema_and_identity(manifest: dict[str, Any]) -> None:
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["schema_version"] == 1
    assert manifest["task_id"] == TASK_ID
    assert manifest["goal_id"] == GOAL_ID
    assert manifest["corpus_id"] == CORPUS_ID
    assert manifest["contracts_schema_version"] == CONTRACTS_SCHEMA
    assert manifest["digest_algorithm"] == "sha256"
    assert manifest["network_policy"] == "offline_reference_only"
    integrity = manifest["integrity"]
    assert integrity["every_artifact_has_source_url_or_cid"] is True
    assert integrity["every_artifact_has_public_status"] is True
    assert integrity["every_artifact_has_rights_privacy_review"] is True
    assert integrity["every_artifact_has_acquisition_date"] is True
    assert integrity["every_artifact_has_label_reviewer_and_version"] is True
    assert integrity["every_artifact_has_split_assignment"] is True
    assert integrity["roles_distinguished"] is True
    assert integrity["synthetic_never_official"] is True
    assert integrity["leakage_checks_required"] is True
    assert integrity["duplicate_family_checks_required"] is True


def test_manifest_distinguishes_official_annotations_and_synthetic(
    manifest: dict[str, Any],
) -> None:
    roles = manifest["artifact_roles"]
    assert set(roles) == ARTIFACT_ROLES

    official = roles["official_bytes"]
    annotation = roles["annotation"]
    synthetic = roles["synthetic_supplement"]

    assert official["may_label_as_official"] is True
    assert official["synthetic_allowed"] is False
    assert official["required_classification"] == "public_official"

    assert annotation["may_label_as_official"] is False
    assert annotation["synthetic_allowed"] is False

    assert synthetic["may_label_as_official"] is False
    assert synthetic["synthetic_allowed"] is True

    seen_roles = {a["role"] for a in _iter_artifacts(manifest)}
    assert ARTIFACT_ROLES <= seen_roles, (
        f"corpus must exercise all roles; missing={sorted(ARTIFACT_ROLES - seen_roles)}"
    )


def test_classification_policy_forbids_private(manifest: dict[str, Any]) -> None:
    policy = manifest["classification_policy"]
    assert set(policy["allowed_classifications"]) == ALLOWED_CLASSIFICATIONS
    assert FORBIDDEN_CLASSIFICATIONS <= set(policy["forbidden_classifications"])
    assert set(policy["allowed_privacy_classes"]) == ALLOWED_PRIVACY_CLASSES
    assert policy["private_real_applications_in_git"] is False
    assert policy["synthetic_must_not_be_labeled_official"] is True


# ---------------------------------------------------------------------------
# Per-artifact required fields
# ---------------------------------------------------------------------------


def test_every_artifact_has_required_metadata(manifest: dict[str, Any]) -> None:
    artifacts = list(_iter_artifacts(manifest))
    assert len(artifacts) >= 6, "expected a diverse multi-artifact corpus"

    for artifact in artifacts:
        aid = artifact["artifact_id"]
        assert isinstance(aid, str) and aid.strip(), "artifact_id required"

        role = artifact["role"]
        assert role in ARTIFACT_ROLES, f"{aid}: unknown role {role!r}"

        assert _has_source_url_or_cid(artifact), (
            f"{aid}: requires source_url and/or source_cid"
        )
        if artifact.get("source_cid"):
            assert _SOURCE_CID_RE.match(str(artifact["source_cid"])), (
                f"{aid}: invalid source_cid {artifact['source_cid']!r}"
            )
        if artifact.get("source_url"):
            url = str(artifact["source_url"])
            assert url.startswith(
                ("https://", "http://", "fixture://")
            ), f"{aid}: unsupported source_url scheme"

        public_status = artifact["public_status"]
        assert public_status in ALLOWED_PUBLIC_STATUS, (
            f"{aid}: public_status {public_status!r}"
        )

        review = artifact["rights_privacy_review"]
        assert isinstance(review, dict), f"{aid}: rights_privacy_review object"
        assert review["status"] == "reviewed", f"{aid}: rights review incomplete"
        assert review["reviewer_id"], f"{aid}: missing rights reviewer"
        assert _RFC3339_UTC_RE.match(str(review["reviewed_at"])), (
            f"{aid}: rights reviewed_at must be RFC3339 UTC"
        )
        assert review.get("pii_scan") == "clear", f"{aid}: pii_scan not clear"
        assert "redistribution_policy" in review or "redistribution_ok" in review

        assert _ISO_DATE_RE.match(str(artifact["acquisition_date"])), (
            f"{aid}: acquisition_date must be YYYY-MM-DD"
        )

        assert artifact["label_reviewer"], f"{aid}: label_reviewer required"
        assert artifact["label_version"], f"{aid}: label_version required"
        assert re.fullmatch(
            r"[0-9]+\.[0-9]+(\.[0-9]+)?", str(artifact["label_version"])
        ) or str(artifact["label_version"]).strip(), (
            f"{aid}: label_version must be non-empty"
        )

        split = artifact["split_assignment"]
        assert split in ALLOWED_SPLITS, f"{aid}: split_assignment {split!r}"

        assert artifact["classification"] in ALLOWED_CLASSIFICATIONS, aid
        assert artifact["privacy_class"] in ALLOWED_PRIVACY_CLASSES, aid
        assert artifact["family_id"], f"{aid}: family_id required"


def test_case_and_artifact_split_and_family_consistency(
    manifest: dict[str, Any],
) -> None:
    for case, artifact in _iter_case_artifacts(manifest):
        assert case["split_assignment"] in ALLOWED_SPLITS
        assert case["family_id"]
        assert artifact["split_assignment"] == case["split_assignment"], (
            f"{artifact['artifact_id']}: split must match case "
            f"{case['case_id']}"
        )
        assert artifact["family_id"] == case["family_id"], (
            f"{artifact['artifact_id']}: family must match case"
        )
        assert case["classification"] in ALLOWED_CLASSIFICATIONS
        assert case["privacy_class"] in ALLOWED_PRIVACY_CLASSES
        assert case["document_family"]
        assert case["application_type"]


def test_official_bytes_never_synthetic_and_vice_versa(
    manifest: dict[str, Any],
) -> None:
    for case, artifact in _iter_case_artifacts(manifest):
        aid = artifact["artifact_id"]
        role = artifact["role"]

        if role == "official_bytes":
            assert artifact["classification"] == "public_official", aid
            assert artifact["privacy_class"] == "approved_public_official", aid
            assert case["privacy_class"] == "approved_public_official", case["case_id"]
            assert not artifact.get("synthetic_marker"), (
                f"{aid}: official_bytes must not carry synthetic_marker"
            )
            assert artifact.get("bytes_policy") != "synthetic_fixture_only", aid

        if role == "synthetic_supplement":
            assert artifact["classification"] == "public_user", aid
            assert artifact["privacy_class"] == "public_synthetic", aid
            assert artifact.get("synthetic_marker"), (
                f"{aid}: synthetic_supplement requires synthetic_marker"
            )
            assert "SYNTHETIC" in str(artifact["synthetic_marker"]).upper()
            assert case["privacy_class"] == "public_synthetic"

        if role == "annotation":
            # Annotations are labels, not official source bytes.
            assert artifact["classification"] == "public_user", aid


def test_corpus_coverage_document_families_and_label_targets(
    manifest: dict[str, Any],
) -> None:
    families = {c["document_family"] for c in manifest["cases"]}
    missing_families = REQUIRED_DOCUMENT_FAMILIES - families
    assert not missing_families, (
        f"missing document families: {sorted(missing_families)}"
    )

    declared = set(manifest.get("document_families_required", []))
    assert REQUIRED_DOCUMENT_FAMILIES <= declared

    label_keys_seen: set[str] = set()
    for artifact in _iter_artifacts(manifest):
        if artifact["role"] != "annotation":
            continue
        labels = artifact.get("labels") or {}
        assert isinstance(labels, dict), artifact["artifact_id"]
        label_keys_seen.update(labels.keys())
        targets = set(artifact.get("label_targets") or [])
        for key in targets:
            if key in REQUIRED_LABEL_COVERAGE:
                assert key in labels, (
                    f"{artifact['artifact_id']}: label_targets has {key} without labels"
                )

    # Corpus-level label coverage across all annotations.
    missing_labels = REQUIRED_LABEL_COVERAGE - label_keys_seen
    assert not missing_labels, (
        f"annotation labels missing coverage keys: {sorted(missing_labels)}"
    )

    app_types = {c["application_type"] for c in manifest["cases"]}
    for required in ("utility", "design", "plant"):
        assert required in app_types, f"missing application_type {required}"


# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------


def test_leakage_policy_declared(manifest: dict[str, Any]) -> None:
    policy = manifest["leakage_policy"]
    assert policy["mode"] == "source_family_partition_fence"
    rules = set(policy["rules"])
    assert "entire_source_family_in_single_partition" in rules
    assert "development_must_not_share_family_with_evaluation" in rules
    assert "no_cross_partition_source_family_members" in rules

    splits = manifest["splits"]
    assert set(splits["partitions"]) == ALLOWED_SPLITS
    assert set(splits["development_partitions"]) == DEVELOPMENT_SPLITS
    assert set(splits["evaluation_partitions"]) == EVALUATION_SPLITS


def test_leakage_family_and_source_partition_fence(
    manifest: dict[str, Any],
) -> None:
    """Families and official sources must not cross development/evaluation."""
    family_to_split: dict[str, str] = {}
    family_to_case: dict[str, str] = {}

    for case in manifest["cases"]:
        family = case["family_id"]
        split = case["split_assignment"]
        if family in family_to_split:
            assert family_to_split[family] == split, (
                f"family {family} spans splits "
                f"{family_to_split[family]!r} and {split!r}"
            )
            assert family_to_case[family] == case["case_id"], (
                f"family {family} used by multiple cases "
                f"{family_to_case[family]!r} and {case['case_id']!r}"
            )
        else:
            family_to_split[family] = split
            family_to_case[family] = case["case_id"]

    # Development vs evaluation family fence.
    dev_families = {
        f for f, s in family_to_split.items() if s in DEVELOPMENT_SPLITS
    }
    eval_families = {
        f for f, s in family_to_split.items() if s in EVALUATION_SPLITS
    }
    leaked = dev_families & eval_families
    assert not leaked, f"family leakage across dev/eval: {sorted(leaked)}"

    # Official source URL / CID fence across development vs evaluation.
    dev_urls: set[str] = set()
    dev_cids: set[str] = set()
    eval_urls: set[str] = set()
    eval_cids: set[str] = set()

    for case, artifact in _iter_case_artifacts(manifest):
        if artifact["role"] != "official_bytes":
            continue
        split = case["split_assignment"]
        url = str(artifact.get("source_url") or "").strip()
        cid = str(artifact.get("source_cid") or "").strip()
        if split in DEVELOPMENT_SPLITS:
            if url:
                dev_urls.add(url)
            if cid:
                dev_cids.add(cid)
        elif split in EVALUATION_SPLITS:
            if url:
                eval_urls.add(url)
            if cid:
                eval_cids.add(cid)

    assert not (dev_urls & eval_urls), (
        f"official source_url leakage: {sorted(dev_urls & eval_urls)}"
    )
    assert not (dev_cids & eval_cids), (
        f"official source_cid leakage: {sorted(dev_cids & eval_cids)}"
    )


def test_held_out_partition_present_and_nonempty(manifest: dict[str, Any]) -> None:
    held = [c for c in manifest["cases"] if c["split_assignment"] == "held_out"]
    assert held, "held_out partition required for evaluation fence"
    for case in held:
        assert case["family_id"] not in {
            c["family_id"]
            for c in manifest["cases"]
            if c["split_assignment"] in DEVELOPMENT_SPLITS
        }


def test_annotation_labels_not_admitted_as_official_bytes(
    manifest: dict[str, Any],
) -> None:
    official_ids = {
        a["artifact_id"]
        for a in _iter_artifacts(manifest)
        if a["role"] == "official_bytes"
    }
    for artifact in _iter_artifacts(manifest):
        if artifact["role"] != "annotation":
            continue
        assert artifact["artifact_id"] not in official_ids
        assert artifact["role"] != "official_bytes"
        # Annotation source should not be an official_bytes artifact id.
        url = str(artifact.get("source_url") or "")
        for oid in official_ids:
            assert oid not in url or "annotation" in artifact["artifact_id"]


# ---------------------------------------------------------------------------
# Duplicate-family checks
# ---------------------------------------------------------------------------


def test_duplicate_family_policy_declared(manifest: dict[str, Any]) -> None:
    policy = manifest["duplicate_family_policy"]
    assert policy["mode"] == "unique_family_and_official_source"
    rules = set(policy["rules"])
    assert "artifact_id_unique_across_corpus" in rules
    assert "family_id_unique_to_one_case" in rules
    assert "official_source_url_unique_across_corpus" in rules


def test_duplicate_family_and_source_uniqueness(manifest: dict[str, Any]) -> None:
    artifact_ids: list[str] = []
    family_ids: list[str] = []
    case_ids: list[str] = []
    official_urls: list[str] = []
    official_cids: list[str] = []
    official_digests: list[str] = []

    for case in manifest["cases"]:
        case_ids.append(case["case_id"])
        family_ids.append(case["family_id"])
        for artifact in case["artifacts"]:
            artifact_ids.append(artifact["artifact_id"])
            if artifact["role"] == "official_bytes":
                url = str(artifact.get("source_url") or "").strip()
                cid = str(artifact.get("source_cid") or "").strip()
                digest = str(artifact.get("content_sha256") or "").strip()
                if url:
                    official_urls.append(url)
                if cid:
                    official_cids.append(cid)
                if digest:
                    official_digests.append(digest)
                    assert _SHA256_HEX_RE.match(digest), (
                        f"{artifact['artifact_id']}: content_sha256 must be 64 hex"
                    )

    assert len(case_ids) == len(set(case_ids)), "duplicate case_id"
    assert len(artifact_ids) == len(set(artifact_ids)), "duplicate artifact_id"
    assert len(family_ids) == len(set(family_ids)), "duplicate family_id across cases"
    assert len(official_urls) == len(set(official_urls)), (
        "duplicate official source_url"
    )
    assert len(official_cids) == len(set(official_cids)), (
        "duplicate official source_cid"
    )
    assert len(official_digests) == len(set(official_digests)), (
        "duplicate official content_sha256"
    )


# ---------------------------------------------------------------------------
# Privacy / secrets
# ---------------------------------------------------------------------------


def test_no_forbidden_classifications_in_corpus(manifest: dict[str, Any]) -> None:
    def walk_classifications(value: Any) -> Iterator[str]:
        if isinstance(value, Mapping):
            # Skip the policy allow/deny lists; check instance classification fields.
            for key, item in value.items():
                if key in {
                    "allowed_classifications",
                    "forbidden_classifications",
                    "allowed_privacy_classes",
                }:
                    continue
                if key == "classification":
                    yield str(item)
                else:
                    yield from walk_classifications(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk_classifications(item)

    for classification in walk_classifications(manifest):
        assert classification in ALLOWED_CLASSIFICATIONS, classification
        assert classification not in FORBIDDEN_CLASSIFICATIONS


def test_corpus_contains_no_secret_material(manifest: dict[str, Any]) -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        assert match is None, (
            f"manifest matched secret pattern {pattern.pattern}: {match.group(0)!r}"
        )


def test_splits_cover_all_declared_partitions(manifest: dict[str, Any]) -> None:
    used = {c["split_assignment"] for c in manifest["cases"]}
    assert ALLOWED_SPLITS <= used, (
        f"unused splits: {sorted(ALLOWED_SPLITS - used)}"
    )


def test_every_case_has_at_least_one_annotation_or_official_or_synthetic(
    manifest: dict[str, Any],
) -> None:
    for case in manifest["cases"]:
        roles = {a["role"] for a in case["artifacts"]}
        assert roles, case["case_id"]
        if case["privacy_class"] == "public_synthetic":
            assert "synthetic_supplement" in roles
            assert "official_bytes" not in roles, (
                f"{case['case_id']}: synthetic case must not claim official_bytes"
            )
        else:
            assert "official_bytes" in roles, (
                f"{case['case_id']}: approved-public case needs official_bytes"
            )
            assert "annotation" in roles, (
                f"{case['case_id']}: approved-public case needs annotation"
            )
