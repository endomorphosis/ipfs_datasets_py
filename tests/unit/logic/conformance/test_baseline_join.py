"""Join and seal the current-state logic-parser baseline (LFP-005).

``LogicParserBaselineReceipt@1`` binds the four Wave-0 inventory artifacts:

* ``LogicSurfaceInventory@1`` — ``parser_inventory.json``
* ``LogicConformanceCorpus@1`` — ``tests/fixtures/logic_conformance/manifest.json``
* ``LogicFamilyAudit@1`` — ``family_label_audit.json``
* ``LogicCapabilityMatrix@1`` — ``capability_matrix.json``

Acceptance (fail-closed):

* Join rejects revision, digest, and schema drift between sealed reports and
  live re-materialization.
* Every unknown label is listed explicitly; the receipt records
  ``hidden_or_silently_normalized_count == 0`` and an empty hidden list.
  Unknown corpus labels keep their observed strings; audit unknowns stay
  ``kind=unknown`` and are never rewritten to a semantic family.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from ipfs_datasets_py.logic.conformance.corpus import (
    LOGIC_CONFORMANCE_CORPUS_INTERFACE,
    LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
    CorpusError,
    LabelDisposition,
    default_manifest_path,
    load_corpus,
)
from ipfs_datasets_py.logic.conformance.inventory import (
    LOGIC_SURFACE_INVENTORY_INTERFACE,
    LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION,
    InventoryError,
    build_parser_inventory_report,
    default_baseline_report_path as inventory_baseline_path,
    default_logic_package_root,
    inventory_logic_surfaces,
    load_parser_inventory,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    INTERFACE as MATRIX_INTERFACE,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    SCHEMA_VERSION as MATRIX_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    AvailabilityStatus,
    CapabilityMatrixError,
    SupportStatus,
    build_default_matrix,
    default_baseline_path as matrix_baseline_path,
    load_matrix_baseline,
    render_matrix_seal_json,
    to_matrix_seal_dict,
)
from ipfs_datasets_py.logic.families.audit import (
    AUDIT_INTERFACE,
    AUDIT_SCHEMA_VERSION,
    FamilyLabelKind,
    baseline_audit_dict,
    default_baseline_report_path as audit_baseline_path,
    load_audit_report,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY

# ---------------------------------------------------------------------------
# LogicParserBaselineReceipt@1
# ---------------------------------------------------------------------------

BASELINE_RECEIPT_INTERFACE: Final = "LogicParserBaselineReceipt@1"
BASELINE_RECEIPT_SCHEMA_VERSION: Final = "logic-parser-baseline-receipt/v1"
BASELINE_TASK_ID: Final = "LFP-005"
BASELINE_GOAL_ID: Final = "LFP-G010"
BASELINE_PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v1"

DATASETS_ROOT: Final = Path(__file__).resolve().parents[4]
BASELINE_DIR: Final = (
    DATASETS_ROOT / "docs" / "architecture" / "logic" / "logic_parser_baseline"
)
README_PATH: Final = BASELINE_DIR / "README.md"
INVENTORY_PATH: Final = BASELINE_DIR / "parser_inventory.json"
AUDIT_PATH: Final = BASELINE_DIR / "family_label_audit.json"
MATRIX_PATH: Final = BASELINE_DIR / "capability_matrix.json"
CORPUS_PATH: Final = (
    DATASETS_ROOT / "tests" / "fixtures" / "logic_conformance" / "manifest.json"
)
LOGIC_ROOT: Final = DATASETS_ROOT / "ipfs_datasets_py" / "logic"

ARTIFACT_KEYS: Final = (
    "parser_inventory",
    "conformance_corpus",
    "family_label_audit",
    "capability_matrix",
)


class BaselineJoinError(ValueError):
    """Raised when baseline join detects revision, digest, or schema drift."""


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BaselineJoinError(f"{label} must be a mapping")
    return dict(value)


def _stable_unique(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _relative_to_datasets(path: Path) -> str:
    try:
        return path.resolve().relative_to(DATASETS_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselineJoinError(f"missing baseline artifact: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _require_mapping(payload, path.name)


def _assert_schema(
    payload: Mapping[str, Any],
    *,
    interface: str,
    schema_version: str,
    label: str,
    version_field: str | None = None,
    expected_version: str | None = None,
) -> None:
    if payload.get("interface") != interface:
        raise BaselineJoinError(
            f"{label} interface drift: expected {interface!r}, "
            f"got {payload.get('interface')!r}"
        )
    if payload.get("schema_version") != schema_version:
        raise BaselineJoinError(
            f"{label} schema drift: expected {schema_version!r}, "
            f"got {payload.get('schema_version')!r}"
        )
    if version_field is not None and expected_version is not None:
        if payload.get(version_field) != expected_version:
            raise BaselineJoinError(
                f"{label} revision drift: expected {version_field}="
                f"{expected_version!r}, got {payload.get(version_field)!r}"
            )


def _collect_corpus_unknowns(corpus: Any) -> tuple[str, ...]:
    labels = list(corpus.unknown_labels())
    # Every unknown-disposition fixture must surface its original family_label.
    for fixture in corpus.fixtures:
        if fixture.label_disposition is LabelDisposition.UNKNOWN:
            if fixture.family_label not in labels:
                raise BaselineJoinError(
                    f"hidden unknown corpus label {fixture.family_label!r} "
                    f"on fixture {fixture.fixture_id!r}"
                )
            if fixture.family_id is not None:
                raise BaselineJoinError(
                    f"silently normalized unknown corpus label "
                    f"{fixture.family_label!r} to family_id "
                    f"{fixture.family_id!r}"
                )
    return tuple(labels)


def _collect_audit_unknowns(audit: Mapping[str, Any]) -> tuple[str, ...]:
    classifications = audit.get("classifications", ())
    if not isinstance(classifications, Sequence) or isinstance(
        classifications, (str, bytes, bytearray)
    ):
        raise BaselineJoinError("audit classifications must be a sequence")

    unknowns: list[str] = []
    for row in classifications:
        if not isinstance(row, Mapping):
            raise BaselineJoinError("audit classification rows must be mappings")
        if row.get("kind") != FamilyLabelKind.UNKNOWN.value:
            continue
        observed = row.get("observed")
        if not isinstance(observed, str) or not observed:
            raise BaselineJoinError(
                "unknown audit classification missing observed label"
            )
        # Fail closed on silent upgrade to a semantic family.
        if row.get("is_semantic_family") is True:
            raise BaselineJoinError(
                f"silently normalized unknown audit label {observed!r} "
                "to a semantic family"
            )
        if row.get("canonical_family_id") not in (None, ""):
            raise BaselineJoinError(
                f"silently normalized unknown audit label {observed!r} "
                f"to canonical_family_id {row.get('canonical_family_id')!r}"
            )
        unknowns.append(observed)

    # Summary kind_counts must not under-count unknowns (hidden rows).
    summary = audit.get("summary") or {}
    if isinstance(summary, Mapping):
        kind_counts = summary.get("kind_counts") or {}
        if isinstance(kind_counts, Mapping):
            declared = int(kind_counts.get("unknown", 0))
            if declared != len(unknowns):
                raise BaselineJoinError(
                    "audit unknown label count drift: summary reports "
                    f"{declared} but classifications list {len(unknowns)}"
                )
    return _stable_unique(unknowns)


def _ui_active_work(matrix: Any) -> dict[str, Any]:
    ui_cells = matrix.cells_for_domain("ui_ux_ir")
    if not ui_cells:
        raise BaselineJoinError("capability matrix missing ui_ux_ir domain cells")
    if not all(cell.support is SupportStatus.DECLARATION_ONLY for cell in ui_cells):
        raise BaselineJoinError(
            "ui_ux_ir cells must remain declaration_only until source import"
        )
    if not all(
        cell.availability is AvailabilityStatus.SOURCE_MISSING for cell in ui_cells
    ):
        raise BaselineJoinError(
            "ui_ux_ir cells must remain source_missing until source import"
        )
    return {
        "domain_id": "ui_ux_ir",
        "status": "declaration_only",
        "availability": "source_missing",
        "source_in_pinned_revision": False,
        "cell_count": len(ui_cells),
        "refill_eligible_count": sum(1 for cell in ui_cells if cell.refill_eligible),
        "policy": (
            "ui_ux_ir is active uncommitted work outside the pinned tree; "
            "LFP-038 owns the source gate. Baseline join records the domain "
            "as declaration-only/source-missing and never invents package files."
        ),
    }


def join_baseline_receipt(
    *,
    inventory_path: Path | None = None,
    corpus_path: Path | None = None,
    audit_path: Path | None = None,
    matrix_path: Path | None = None,
    logic_root: Path | None = None,
    verify_live: bool = True,
) -> dict[str, Any]:
    """Join the four baseline artifacts into a content-addressed receipt.

    When ``verify_live`` is true (default), each sealed report is compared to
    live re-materialization. Any schema, revision, or digest disagreement
    raises :class:`BaselineJoinError`.
    """

    inv_path = Path(inventory_path) if inventory_path else INVENTORY_PATH
    cor_path = Path(corpus_path) if corpus_path else CORPUS_PATH
    aud_path = Path(audit_path) if audit_path else AUDIT_PATH
    mat_path = Path(matrix_path) if matrix_path else MATRIX_PATH
    root = Path(logic_root) if logic_root is not None else LOGIC_ROOT

    try:
        inventory_report = load_parser_inventory(inv_path)
    except InventoryError as exc:
        raise BaselineJoinError(
            f"parser_inventory schema drift or load failure: {exc}"
        ) from exc
    _assert_schema(
        inventory_report,
        interface=LOGIC_SURFACE_INVENTORY_INTERFACE,
        schema_version=LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION,
        label="parser_inventory",
        version_field="task_id",
        expected_version="LFP-001",
    )
    if inventory_report.get("goal_id") != BASELINE_GOAL_ID:
        raise BaselineJoinError(
            f"parser_inventory revision drift: goal_id expected "
            f"{BASELINE_GOAL_ID!r}, got {inventory_report.get('goal_id')!r}"
        )

    try:
        corpus = load_corpus(cor_path)
    except CorpusError as exc:
        raise BaselineJoinError(
            f"conformance_corpus schema drift or load failure: {exc}"
        ) from exc
    corpus_dict = corpus.to_dict()
    _assert_schema(
        corpus_dict,
        interface=LOGIC_CONFORMANCE_CORPUS_INTERFACE,
        schema_version=LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION,
        label="conformance_corpus",
        version_field="task",
        expected_version="LFP-002",
    )
    if corpus.objective != BASELINE_GOAL_ID:
        raise BaselineJoinError(
            f"conformance_corpus revision drift: objective expected "
            f"{BASELINE_GOAL_ID!r}, got {corpus.objective!r}"
        )

    audit_report = load_audit_report(aud_path)
    _assert_schema(
        audit_report,
        interface=AUDIT_INTERFACE,
        schema_version=AUDIT_SCHEMA_VERSION,
        label="family_label_audit",
        version_field="report_version",
        expected_version="1.0.0",
    )

    matrix_seal = _load_json(mat_path)
    _assert_schema(
        matrix_seal,
        interface=MATRIX_INTERFACE,
        schema_version=MATRIX_SCHEMA_VERSION,
        label="capability_matrix",
        version_field="version",
        expected_version="1.0.0",
    )
    try:
        matrix = load_matrix_baseline(mat_path)
    except CapabilityMatrixError as exc:
        raise BaselineJoinError(
            f"capability_matrix digest drift or seal failure: {exc}"
        ) from exc

    if verify_live:
        live_inventory = inventory_logic_surfaces(logic_root=root)
        live_inventory_report = build_parser_inventory_report(live_inventory)
        if inventory_report != live_inventory_report:
            raise BaselineJoinError(
                "parser_inventory digest/content drift against live inventory"
            )
        if inventory_report.get("content_digest") != live_inventory.content_digest():
            raise BaselineJoinError(
                "parser_inventory content_digest disagrees with live inventory"
            )

        on_disk_corpus = json.loads(cor_path.read_text(encoding="utf-8"))
        if not isinstance(on_disk_corpus, Mapping):
            raise BaselineJoinError("conformance corpus must be a JSON object")
        if corpus.to_dict() != dict(on_disk_corpus):
            # Round-trip may drop optional defaults; require digest identity.
            reloaded = load_corpus(cor_path)
            if reloaded.content_digest() != corpus.content_digest():
                raise BaselineJoinError(
                    "conformance_corpus digest drift against sealed manifest"
                )
        # Seal digest is the corpus content digest of the sealed path.
        sealed_digest = corpus.content_digest()
        if load_corpus(cor_path).content_digest() != sealed_digest:
            raise BaselineJoinError("conformance_corpus non-deterministic digest")

        live_audit = baseline_audit_dict()
        if audit_report != live_audit:
            raise BaselineJoinError(
                "family_label_audit digest/content drift against live audit"
            )

        live_matrix = build_default_matrix()
        if matrix.to_dict() != live_matrix.to_dict():
            raise BaselineJoinError(
                "capability_matrix digest/content drift against live matrix"
            )
        expected_seal = to_matrix_seal_dict(live_matrix)
        if matrix_seal != expected_seal:
            raise BaselineJoinError(
                "capability_matrix seal disagrees with live materialization"
            )
        if matrix_seal.get("content_digest_sha256") != live_matrix.content_digest():
            raise BaselineJoinError(
                "capability_matrix content_digest_sha256 disagrees with live matrix"
            )
        if mat_path.read_text(encoding="utf-8") != render_matrix_seal_json(live_matrix):
            raise BaselineJoinError(
                "capability_matrix sealed bytes disagree with live seal rendering"
            )

    corpus_unknowns = _collect_corpus_unknowns(corpus)
    audit_unknowns = _collect_audit_unknowns(audit_report)
    # Explicit zero: join never hides or rewrites unknowns at seal time.
    hidden_or_silently_normalized: list[str] = []

    unknown_labels = {
        "corpus": list(corpus_unknowns),
        "audit": list(audit_unknowns),
        "all": list(_stable_unique([*corpus_unknowns, *audit_unknowns])),
        "hidden_or_silently_normalized": list(hidden_or_silently_normalized),
        "hidden_or_silently_normalized_count": len(hidden_or_silently_normalized),
        "corpus_unknown_count": len(corpus_unknowns),
        "audit_unknown_count": len(audit_unknowns),
    }
    if unknown_labels["hidden_or_silently_normalized_count"] != 0:
        raise BaselineJoinError(
            "join recorded hidden or silently normalized unknown labels: "
            f"{unknown_labels['hidden_or_silently_normalized']!r}"
        )

    audit_summary = dict(audit_report.get("summary") or {})
    gaps = {
        "matrix_unknown_count": len(matrix.unknown_cells()),
        "matrix_unimplemented_count": len(matrix.unimplemented_cells()),
        "matrix_refill_count": len(matrix.refill_cells()),
        "audit_drift_count": int(audit_summary.get("drift_count", 0)),
        "audit_unknown_count": len(audit_unknowns),
        "corpus_unknown_label_count": len(corpus_unknowns),
        "inventory_missing_evidence_families": list(
            inventory_report.get("evidence_coverage", {}).get("missing_families", [])
        ),
        "semantic_family_misuse_count": int(
            audit_summary.get("semantic_family_misuse_count", 0)
        ),
    }
    if gaps["semantic_family_misuse_count"] != 0:
        raise BaselineJoinError(
            "join rejects semantic-family misuse in the audit baseline"
        )
    if gaps["inventory_missing_evidence_families"]:
        raise BaselineJoinError(
            "join rejects incomplete inventory evidence coverage: "
            f"{gaps['inventory_missing_evidence_families']!r}"
        )

    ui_work = _ui_active_work(matrix)

    artifacts = {
        "parser_inventory": {
            "path": _relative_to_datasets(inv_path),
            "interface": inventory_report["interface"],
            "schema_version": inventory_report["schema_version"],
            "task_id": inventory_report.get("task_id"),
            "goal_id": inventory_report.get("goal_id"),
            "content_digest": inventory_report["content_digest"],
            "surface_count": inventory_report.get("surface_count"),
            "scanned_file_count": inventory_report.get("scanned_file_count"),
        },
        "conformance_corpus": {
            "path": _relative_to_datasets(cor_path),
            "interface": corpus.interface,
            "schema_version": corpus.schema_version,
            "task_id": corpus.task,
            "goal_id": corpus.objective,
            "content_digest": corpus.content_digest(),
            "fixture_count": len(corpus),
            "corpus_id": corpus.corpus_id,
            "version": corpus.version,
        },
        "family_label_audit": {
            "path": _relative_to_datasets(aud_path),
            "interface": audit_report["interface"],
            "schema_version": audit_report["schema_version"],
            "report_version": audit_report.get("report_version"),
            "content_digest": _canonical_digest(audit_report),
            "classification_count": audit_summary.get("classification_count"),
            "drift_count": audit_summary.get("drift_count"),
            "unique_label_count": audit_summary.get("unique_label_count"),
            "roots": list(audit_report.get("roots") or ()),
        },
        "capability_matrix": {
            "path": _relative_to_datasets(mat_path),
            "interface": matrix.interface,
            "schema_version": matrix.schema_version,
            "version": matrix.version,
            "content_digest": matrix.content_digest(),
            "cell_count": len(matrix.cells),
            "unknown_count": len(matrix.unknown_cells()),
            "refill_count": len(matrix.refill_cells()),
            "materialization": matrix_seal.get("materialization"),
        },
    }

    receipt: dict[str, Any] = {
        "interface": BASELINE_RECEIPT_INTERFACE,
        "schema_version": BASELINE_RECEIPT_SCHEMA_VERSION,
        "task_id": BASELINE_TASK_ID,
        "goal_id": BASELINE_GOAL_ID,
        "program_id": BASELINE_PROGRAM_ID,
        "description": (
            "Joined current-state baseline binding parser inventory, "
            "conformance corpus, family-label audit, and capability matrix. "
            "Unknown labels are listed explicitly; hidden or silently "
            "normalized unknowns are rejected."
        ),
        "canonical_family_ids": sorted(DEFAULT_REGISTRY.families),
        "artifacts": artifacts,
        "unknown_labels": unknown_labels,
        "gaps": gaps,
        "active_ui_work": ui_work,
        "roots": {
            "logic_package": _relative_to_datasets(root)
            if root.exists()
            else root.as_posix(),
            "baseline_directory": _relative_to_datasets(BASELINE_DIR),
            "audit_roots": list(audit_report.get("roots") or ()),
            "inventory_policy_profile_id": inventory_report.get("policy_profile_id"),
        },
    }
    receipt["content_digest"] = _canonical_digest(receipt)
    return receipt


def validate_baseline_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed when a receipt is malformed or hides unknown labels."""

    payload = _require_mapping(receipt, "receipt")
    _assert_schema(
        payload,
        interface=BASELINE_RECEIPT_INTERFACE,
        schema_version=BASELINE_RECEIPT_SCHEMA_VERSION,
        label="baseline_receipt",
        version_field="task_id",
        expected_version=BASELINE_TASK_ID,
    )
    if payload.get("goal_id") != BASELINE_GOAL_ID:
        raise BaselineJoinError(
            f"baseline_receipt revision drift: goal_id expected "
            f"{BASELINE_GOAL_ID!r}, got {payload.get('goal_id')!r}"
        )
    artifacts = _require_mapping(payload.get("artifacts"), "receipt.artifacts")
    for key in ARTIFACT_KEYS:
        if key not in artifacts:
            raise BaselineJoinError(f"receipt missing artifact {key!r}")
        art = _require_mapping(artifacts[key], f"receipt.artifacts.{key}")
        for field in ("interface", "schema_version", "content_digest", "path"):
            if not art.get(field):
                raise BaselineJoinError(
                    f"receipt artifact {key!r} missing required field {field!r}"
                )

    unknowns = _require_mapping(payload.get("unknown_labels"), "receipt.unknown_labels")
    hidden = unknowns.get("hidden_or_silently_normalized")
    if not isinstance(hidden, list):
        raise BaselineJoinError(
            "receipt.unknown_labels.hidden_or_silently_normalized must be a list"
        )
    count = unknowns.get("hidden_or_silently_normalized_count")
    if count != 0 or len(hidden) != 0:
        raise BaselineJoinError(
            "receipt must list zero hidden or silently normalized unknown "
            f"labels; got count={count!r} labels={hidden!r}"
        )
    for key in ("corpus", "audit", "all"):
        value = unknowns.get(key)
        if not isinstance(value, list):
            raise BaselineJoinError(
                f"receipt.unknown_labels.{key} must be an explicit list"
            )

    body = {key: value for key, value in payload.items() if key != "content_digest"}
    expected = _canonical_digest(body)
    if payload.get("content_digest") != expected:
        raise BaselineJoinError(
            "receipt content_digest disagrees with canonical body "
            f"(digest drift): expected {expected!r}, got "
            f"{payload.get('content_digest')!r}"
        )


# ---------------------------------------------------------------------------
# Path / documentation contracts
# ---------------------------------------------------------------------------


def test_baseline_paths_resolve_to_checked_in_artifacts() -> None:
    assert INVENTORY_PATH.is_file()
    assert AUDIT_PATH.is_file()
    assert MATRIX_PATH.is_file()
    assert CORPUS_PATH.is_file()
    assert README_PATH.is_file()
    assert inventory_baseline_path(LOGIC_ROOT) == INVENTORY_PATH
    assert audit_baseline_path() == AUDIT_PATH
    assert matrix_baseline_path(datasets_root=DATASETS_ROOT) == MATRIX_PATH
    assert default_manifest_path() == CORPUS_PATH
    assert default_logic_package_root(DATASETS_ROOT) == LOGIC_ROOT


def test_readme_documents_join_contract_and_artifacts() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    for needle in (
        "LogicParserBaselineReceipt@1",
        "parser_inventory.json",
        "family_label_audit.json",
        "capability_matrix.json",
        "manifest.json",
        "hidden or silently normalized",
        "revision",
        "digest",
        "schema",
        "LFP-005",
        "ui_ux_ir",
        "zero",
    ):
        assert needle in text, f"README missing required documentation: {needle!r}"


# ---------------------------------------------------------------------------
# Successful join
# ---------------------------------------------------------------------------


def test_join_seals_current_baseline_without_drift() -> None:
    before = {
        path: path.read_bytes()
        for path in (INVENTORY_PATH, AUDIT_PATH, MATRIX_PATH, CORPUS_PATH, README_PATH)
    }

    receipt = join_baseline_receipt(verify_live=True)
    validate_baseline_receipt(receipt)

    assert receipt["interface"] == BASELINE_RECEIPT_INTERFACE
    assert receipt["schema_version"] == BASELINE_RECEIPT_SCHEMA_VERSION
    assert receipt["task_id"] == BASELINE_TASK_ID
    assert receipt["goal_id"] == BASELINE_GOAL_ID
    assert receipt["program_id"] == BASELINE_PROGRAM_ID
    assert set(receipt["artifacts"]) == set(ARTIFACT_KEYS)
    assert receipt["canonical_family_ids"] == sorted(DEFAULT_REGISTRY.families)

    unknowns = receipt["unknown_labels"]
    assert unknowns["hidden_or_silently_normalized"] == []
    assert unknowns["hidden_or_silently_normalized_count"] == 0
    assert "typed_first_order" in unknowns["corpus"]
    assert "workflow_temporal" in unknowns["corpus"]
    assert unknowns["corpus_unknown_count"] == len(unknowns["corpus"])
    assert unknowns["audit_unknown_count"] == len(unknowns["audit"])
    assert set(unknowns["all"]) == set(unknowns["corpus"]) | set(unknowns["audit"])

    gaps = receipt["gaps"]
    assert gaps["semantic_family_misuse_count"] == 0
    assert gaps["inventory_missing_evidence_families"] == []
    assert gaps["matrix_refill_count"] >= gaps["matrix_unknown_count"]
    assert gaps["corpus_unknown_label_count"] == len(unknowns["corpus"])
    assert gaps["audit_unknown_count"] == len(unknowns["audit"])

    ui = receipt["active_ui_work"]
    assert ui["domain_id"] == "ui_ux_ir"
    assert ui["status"] == "declaration_only"
    assert ui["availability"] == "source_missing"
    assert ui["source_in_pinned_revision"] is False
    assert ui["cell_count"] > 0

    # Join is side-effect free against sealed artifacts and documentation.
    after = {
        path: path.read_bytes()
        for path in (INVENTORY_PATH, AUDIT_PATH, MATRIX_PATH, CORPUS_PATH, README_PATH)
    }
    assert before == after

    again = join_baseline_receipt(verify_live=True)
    assert again == receipt
    assert again["content_digest"] == receipt["content_digest"]


def test_join_explicitly_lists_all_unknown_labels_without_normalization() -> None:
    receipt = join_baseline_receipt(verify_live=True)
    corpus = load_corpus(CORPUS_PATH)
    audit = load_audit_report(AUDIT_PATH)

    # Corpus: every unknown-disposition fixture label is listed, unmodified.
    for fixture in corpus.fixtures:
        if fixture.label_disposition is LabelDisposition.UNKNOWN:
            assert fixture.family_label in receipt["unknown_labels"]["corpus"]
            assert fixture.family_id is None
            # Original observed string is preserved (no case/alias rewrite).
            assert isinstance(fixture.family_label, str)
            assert fixture.family_label  # non-empty observed label

    # Audit: every kind=unknown classification is listed; none is a family.
    audit_unknowns = {
        row["observed"]
        for row in audit["classifications"]
        if row["kind"] == FamilyLabelKind.UNKNOWN.value
    }
    assert set(receipt["unknown_labels"]["audit"]) == audit_unknowns
    for label in audit_unknowns:
        row = next(
            item
            for item in audit["classifications"]
            if item["observed"] == label
            and item["kind"] == FamilyLabelKind.UNKNOWN.value
        )
        assert row["is_semantic_family"] is False
        assert row["canonical_family_id"] is None

    assert receipt["unknown_labels"]["hidden_or_silently_normalized_count"] == 0
    assert receipt["unknown_labels"]["hidden_or_silently_normalized"] == []


# ---------------------------------------------------------------------------
# Drift rejection
# ---------------------------------------------------------------------------


def test_join_rejects_schema_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "parser_inventory.json"
    payload = load_parser_inventory(INVENTORY_PATH)
    payload["schema_version"] = "logic-surface-inventory/v0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="schema drift"):
        join_baseline_receipt(inventory_path=drifted, verify_live=False)


def test_join_rejects_schema_drift_via_assert_helper(tmp_path: Path) -> None:
    """Corpus schema is checked after load; wrong schema_version fails closed."""

    drifted = tmp_path / "manifest.json"
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    payload["schema_version"] = "logic-conformance-corpus/v0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="schema drift"):
        join_baseline_receipt(corpus_path=drifted, verify_live=False)


def test_join_rejects_interface_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "family_label_audit.json"
    payload = load_audit_report(AUDIT_PATH)
    payload["interface"] = "LogicFamilyAudit@0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="interface drift"):
        join_baseline_receipt(audit_path=drifted, verify_live=False)


def test_join_rejects_revision_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "capability_matrix.json"
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    payload["version"] = "0.0.0-drift"
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="revision drift"):
        join_baseline_receipt(matrix_path=drifted, verify_live=False)


def test_join_rejects_inventory_digest_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "parser_inventory.json"
    payload = load_parser_inventory(INVENTORY_PATH)
    payload["content_digest"] = "0" * 64
    # Keep schema/interface valid so the digest check is the failure mode.
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="digest|drift"):
        join_baseline_receipt(inventory_path=drifted, verify_live=True)


def test_join_rejects_matrix_seal_digest_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "capability_matrix.json"
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    payload["content_digest_sha256"] = "0" * 64
    drifted.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="digest|drift|disagree"):
        join_baseline_receipt(matrix_path=drifted, verify_live=True)


def test_join_rejects_audit_content_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "family_label_audit.json"
    payload = load_audit_report(AUDIT_PATH)
    # Mutate a classification without changing schema/interface/version.
    assert payload["classifications"], "audit must have classifications"
    mutated = copy.deepcopy(payload)
    mutated["classifications"] = list(mutated["classifications"])
    first = dict(mutated["classifications"][0])
    first["notes"] = (first.get("notes") or "") + " [drift-injection]"
    mutated["classifications"][0] = first
    drifted.write_text(
        json.dumps(mutated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(BaselineJoinError, match="drift"):
        join_baseline_receipt(audit_path=drifted, verify_live=True)


def test_join_rejects_hidden_unknown_label_in_corpus_summary() -> None:
    """A corpus that drops an unknown label from unknown_labels() is rejected.

    Exercise the collector directly with a fixture-shaped object that claims
    an unknown disposition while omitting the label from the public list.
    """

    class _HiddenUnknownCorpus:
        fixtures = (
            type(
                "F",
                (),
                {
                    "fixture_id": "hidden_case",
                    "family_label": "hidden_unknown_label_xyz",
                    "label_disposition": LabelDisposition.UNKNOWN,
                    "family_id": None,
                },
            )(),
        )

        def unknown_labels(self) -> tuple[str, ...]:
            return ()

    with pytest.raises(BaselineJoinError, match="hidden unknown corpus label"):
        _collect_corpus_unknowns(_HiddenUnknownCorpus())


def test_join_rejects_silently_normalized_unknown_corpus_label() -> None:
    class _NormalizedCorpus:
        fixtures = (
            type(
                "F",
                (),
                {
                    "fixture_id": "normalized_case",
                    "family_label": "typed_first_order",
                    "label_disposition": LabelDisposition.UNKNOWN,
                    "family_id": "first_order",
                },
            )(),
        )

        def unknown_labels(self) -> tuple[str, ...]:
            return ("typed_first_order",)

    with pytest.raises(BaselineJoinError, match="silently normalized unknown corpus"):
        _collect_corpus_unknowns(_NormalizedCorpus())


def test_join_rejects_silently_normalized_unknown_audit_label() -> None:
    audit = {
        "classifications": [
            {
                "observed": "totally_free_form_xyz",
                "normalized": "totally_free_form_xyz",
                "kind": "unknown",
                "is_semantic_family": True,
                "canonical_family_id": "first_order",
            }
        ],
        "summary": {"kind_counts": {"unknown": 1}},
    }
    with pytest.raises(BaselineJoinError, match="silently normalized unknown audit"):
        _collect_audit_unknowns(audit)


def test_validate_receipt_rejects_nonzero_hidden_unknowns() -> None:
    receipt = join_baseline_receipt(verify_live=False)
    receipt["unknown_labels"] = dict(receipt["unknown_labels"])
    receipt["unknown_labels"]["hidden_or_silently_normalized"] = ["sneaky_label"]
    receipt["unknown_labels"]["hidden_or_silently_normalized_count"] = 1
    # Recompute digest so only the hidden-label rule fails, not digest drift.
    body = {key: value for key, value in receipt.items() if key != "content_digest"}
    receipt["content_digest"] = _canonical_digest(body)
    with pytest.raises(BaselineJoinError, match="zero hidden or silently normalized"):
        validate_baseline_receipt(receipt)


def test_validate_receipt_rejects_digest_drift() -> None:
    receipt = join_baseline_receipt(verify_live=False)
    receipt = dict(receipt)
    receipt["content_digest"] = "sha256:" + ("0" * 64)
    with pytest.raises(BaselineJoinError, match="digest drift"):
        validate_baseline_receipt(receipt)


def test_artifact_interfaces_match_wave0_contracts() -> None:
    receipt = join_baseline_receipt(verify_live=False)
    assert (
        receipt["artifacts"]["parser_inventory"]["interface"]
        == LOGIC_SURFACE_INVENTORY_INTERFACE
    )
    assert (
        receipt["artifacts"]["conformance_corpus"]["interface"]
        == LOGIC_CONFORMANCE_CORPUS_INTERFACE
    )
    assert receipt["artifacts"]["family_label_audit"]["interface"] == AUDIT_INTERFACE
    assert receipt["artifacts"]["capability_matrix"]["interface"] == MATRIX_INTERFACE
    assert (
        receipt["artifacts"]["parser_inventory"]["schema_version"]
        == LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION
    )
    assert (
        receipt["artifacts"]["conformance_corpus"]["schema_version"]
        == LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION
    )
    assert (
        receipt["artifacts"]["family_label_audit"]["schema_version"]
        == AUDIT_SCHEMA_VERSION
    )
    assert (
        receipt["artifacts"]["capability_matrix"]["schema_version"]
        == MATRIX_SCHEMA_VERSION
    )
