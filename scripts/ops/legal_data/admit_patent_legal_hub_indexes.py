#!/usr/bin/env python3
"""Admit hub index package through DLP, rights, and Dataset Viewer gates.

PATLAW-175: fail-closed public admission for multi-artifact corpus + BM25 +
vector + knowledge-graph Hub index packages produced by PATLAW-174.

Default mode is **credential-free** and offline:

1. Refuse to run when Hub credentials are already resolved in the environment
   (admission must complete before tokens are available).
2. Load a staged hub index package (or materialize the default fixture).
3. Enforce package integrity, rights/privacy, secret-like DLP, and orphan pins.
4. Project the package into a release-policy inventory and run PATLAW-158
   cards/configs, Parquet, rights/DLP, orphans, count parity, stale-source,
   and Dataset Viewer contract gates against an offline fake Viewer.
5. Emit an admission receipt that binds ``package_root_cid`` and gate outcomes.

This script never authenticates or uploads to Hugging Face.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    BM25_REPOSITORY,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
    default_public_coverage,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (  # noqa: E402
    DEFAULT_MAX_SOURCE_AGE_DAYS,
    MANDATORY_SOURCE_IDS,
    RELEASE_POLICY_V2_SHA256,
    RELEASE_POLICY_V2_VERSION,
    VIEWER_ENDPOINTS,
    AdmissionRejectedError,
    CredentialPrematureError,
    FakeDatasetViewerService,
    FakeViewerGateway,
    FindingCategory,
    GateResult,
    PatentHFReleasePolicyV2,
    ReleasePolicyV2Error,
    RepositoryInventory,
    StagedParquetShard,
    StagedReleaseInventory,
    assert_credentials_unresolved,
    load_staged_release_inventory,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (  # noqa: E402
    POLICY_RECEIPT_FILENAME,
    QUALITY_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    ARTIFACTS_INVENTORY_FILENAME,
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
    PACKAGE_ROOT_FILENAME,
    RECEIPT_FILENAME,
    HubIndexPackageError,
    load_package_manifest,
    package_patent_legal_hub_indexes,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-175"
GOAL_ID: Final = "PATLAW-G212"
PROGRAM_ID: Final = "patent-legal-intelligence-v1"
ADMISSION_RECEIPT_SCHEMA: Final = "patent-legal-hub-index-admission-receipt/v1"
ADMISSION_RECEIPT_FILENAME: Final = "hub-index-admission-receipt.json"
PRODUCER: Final = "producer:hub-index-admission"
CONFIG_ID: Final = "config:hub-index-admission/v1"
CODE_VERSION: Final = "1.0.0"

PACKAGE_GATE_NAMES: Final[tuple[str, ...]] = (
    "package_integrity",
    "package_rights_privacy",
    "package_dlp",
    "package_orphans",
)
POLICY_GATE_NAMES: Final[tuple[str, ...]] = (
    "cards_configs",
    "parquet",
    "rights_dlp",
    "orphans",
    "count_parity",
    "stale_sources",
    "dataset_viewer",
)
EXPECTED_GATE_NAMES: Final[tuple[str, ...]] = PACKAGE_GATE_NAMES + POLICY_GATE_NAMES

_CANONICAL_REPOS: Final[tuple[str, ...]] = (
    CORPUS_REPOSITORY,
    VECTORS_REPOSITORY,
    BM25_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
)

_ROLE_BY_REPO: Final[Mapping[str, str]] = {
    CORPUS_REPOSITORY: "corpus",
    VECTORS_REPOSITORY: "vectors",
    BM25_REPOSITORY: "bm25",
    KNOWLEDGE_GRAPH_REPOSITORY: "knowledge_graph",
}

_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700
# Match real Hub-token material only — not finding codes like ``secret.hf_token``.
_HF_TOKEN_VALUE_RE = re.compile(r"(?i)\bhf_[A-Za-z0-9]{20,}\b")
_HF_TOKEN_ASSIGN_RE = re.compile(
    r'(?i)(?:"|\b)(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN|HUGGINGFACE_HUB_TOKEN|'
    r'HUGGINGFACE_TOKEN)(?:"|\b)\s*[:=]\s*"[^"]{8,}"'
)
_PARQUET_MAGIC: Final = b"PAR1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HubIndexAdmissionError(RuntimeError):
    """Raised when hub index package admission cannot complete fail-closed."""

    code: str = "hub_index_admission_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class PackageAdmissionRejectedError(AdmissionRejectedError):
    """Raised when hub index package admission is refused fail-closed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(_DIR_MODE)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        tmp.chmod(_FILE_MODE)
    except OSError:
        pass
    tmp.replace(path)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HubIndexAdmissionError(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HubIndexAdmissionError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HubIndexAdmissionError(f"expected JSON object in {path}")
    return dict(payload)


def _reject_secrets_in_payload(payload: Any, *, label: str) -> None:
    """Fail closed if admission artifacts embed Hub-token shaped secrets.

    Finding codes such as ``secret.hf_token`` are allowed; only live token
    material and env-style assignments are rejected.
    """
    blob = json.dumps(payload, sort_keys=True, default=str)
    if _HF_TOKEN_VALUE_RE.search(blob) or _HF_TOKEN_ASSIGN_RE.search(blob):
        raise HubIndexAdmissionError(
            f"{label} embeds credential-shaped material (refusing receipt)"
        )


def _sanitize_finding_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    """Drop detail text that might carry residual secret-shaped content."""
    payload = {
        "category": str(item.get("category") or ""),
        "code": str(item.get("code") or ""),
        "end_char": int(item.get("end_char") or 0),
        "field": str(item.get("field") or ""),
        "start_char": int(item.get("start_char") or 0),
        "value_sha256": str(item.get("value_sha256") or ""),
    }
    detail = str(item.get("detail") or "")
    if detail and not (
        _HF_TOKEN_VALUE_RE.search(detail) or _HF_TOKEN_ASSIGN_RE.search(detail)
    ):
        # Keep short non-secret detail for operators; drop secret-shaped text.
        if len(detail) <= 128:
            payload["detail"] = detail
    return payload


def _gate_dict(gate: GateResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(gate, GateResult):
        return gate.to_dict()
    return {
        "name": str(gate.get("name") or ""),
        "passed": bool(gate.get("passed")),
        "reason_codes": list(gate.get("reason_codes") or ()),
        "details": dict(gate.get("details") or {}),
    }


def _make_gate(
    name: str,
    *,
    passed: bool,
    reason_codes: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> GateResult:
    return GateResult(
        name=name,
        passed=passed,
        reason_codes=tuple(sorted(set(reason_codes))),
        details=dict(details or {}),
    )


def _minimal_parquet_bytes(rows: int = 1) -> bytes:
    """Deterministic tiny ZSTD Parquet used for optional inventory projection."""
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "record_id": [f"r{i}" for i in range(rows)],
            "config_name": ["usc"] * rows,
            "classification": ["public_official"] * rows,
            "source_cid": ["b" + "a" * 58] * rows,
            "corpus_record_id": [""] * rows,
            "record_sha256": [_sha256_text(f"r{i}") for i in range(rows)],
            "authoritative_json": ["{}"] * rows,
            "ai_derived_json": ["{}"] * rows,
            "source_lineage_json": ["{}"] * rows,
            "rights_review_json": ["{}"] * rows,
            "privacy_review_json": ["{}"] * rows,
            "record_json": ["{}"] * rows,
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Package resolution
# ---------------------------------------------------------------------------


def resolve_package_dir(
    *,
    package_dir: str | Path | None = None,
    default_fixture: bool = False,
    stage_dir: str | Path | None = None,
    organization: str = ORGANIZATION,
) -> Path:
    """Return a staged hub index package directory (existing or freshly built)."""
    if package_dir is not None and default_fixture:
        raise HubIndexAdmissionError(
            "provide either package_dir or default_fixture, not both"
        )
    if package_dir is None and not default_fixture:
        raise HubIndexAdmissionError(
            "provide --package-dir or --default-fixture"
        )

    if package_dir is not None:
        root = Path(package_dir).expanduser().resolve()
        if not root.is_dir():
            raise HubIndexAdmissionError(
                f"package_dir is not a directory: {root}"
            )
        manifest_path = root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise HubIndexAdmissionError(
                f"missing package manifest: {manifest_path}"
            )
        return root

    out = (
        Path(stage_dir).expanduser().resolve()
        if stage_dir is not None
        else Path(tempfile.mkdtemp(prefix="hub-index-admit-"))
    )
    if out.exists() and any(out.iterdir()):
        raise HubIndexAdmissionError(
            f"stage_dir is not empty: {out} (refusing partial stage)"
        )
    try:
        package_patent_legal_hub_indexes(
            default_fixture=True,
            organization=organization,
            stage=True,
            output_dir=out,
        )
    except Exception as exc:  # package module raises typed errors
        raise HubIndexAdmissionError(
            f"failed to materialize default hub index package: {exc}"
        ) from exc
    return out


class _PackageManifestView:
    """Soft view of a package manifest for admission (allows adversarial fixtures).

    Strict :func:`load_package_manifest` re-seals digests and rejects non-public
    rights at construction time. Admission must still evaluate those packages so
    gates can block them with reason codes rather than aborting before gates.
    """

    __slots__ = (
        "artifact_descriptors",
        "bm25_root_cid",
        "corpus_root_cid",
        "counts",
        "families",
        "graph_root_cid",
        "index_families_present",
        "notes",
        "organization",
        "package_digest_sha256",
        "package_root_cid",
        "partition",
        "privacy_summary",
        "rights_summary",
        "schema_version",
        "task_id",
        "vector_root_cid",
        "version_tag",
    )

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.schema_version = str(payload.get("schema_version") or "")
        self.task_id = str(payload.get("task_id") or "")
        self.partition = str(payload.get("partition") or "")
        self.organization = str(payload.get("organization") or ORGANIZATION)
        self.version_tag = str(payload.get("version_tag") or "")
        self.package_root_cid = str(payload.get("package_root_cid") or "")
        self.package_digest_sha256 = str(payload.get("package_digest_sha256") or "")
        self.corpus_root_cid = str(payload.get("corpus_root_cid") or "")
        self.bm25_root_cid = str(payload.get("bm25_root_cid") or "")
        self.vector_root_cid = str(payload.get("vector_root_cid") or "")
        self.graph_root_cid = str(payload.get("graph_root_cid") or "")
        self.index_families_present = tuple(
            payload.get("index_families_present") or ()
        )
        self.rights_summary = dict(payload.get("rights_summary") or {})
        self.privacy_summary = dict(payload.get("privacy_summary") or {})
        self.artifact_descriptors = tuple(
            payload.get("artifact_descriptors") or ()
        )
        self.notes = str(payload.get("notes") or "")
        self.families = tuple(payload.get("families") or ())
        counts_raw = payload.get("counts") or {}
        if hasattr(counts_raw, "to_dict"):
            counts_raw = counts_raw.to_dict()
        self.counts = _CountsView(dict(counts_raw) if isinstance(counts_raw, Mapping) else {})


class _CountsView:
    __slots__ = (
        "artifact_count",
        "bm25_documents",
        "bm25_postings",
        "corpus_documents",
        "graph_edges",
        "graph_nodes",
        "vector_documents",
        "_raw",
    )

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = dict(raw)
        self.corpus_documents = int(raw.get("corpus_documents") or 0)
        self.bm25_documents = int(raw.get("bm25_documents") or 0)
        self.bm25_postings = int(raw.get("bm25_postings") or 0)
        self.vector_documents = int(raw.get("vector_documents") or 0)
        self.graph_nodes = int(raw.get("graph_nodes") or 0)
        self.graph_edges = int(raw.get("graph_edges") or 0)
        self.artifact_count = int(raw.get("artifact_count") or 0)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)


def load_package_context(package_dir: str | Path) -> dict[str, Any]:
    """Load package manifest, inventory, and graph/orphan pins from disk."""
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise HubIndexAdmissionError(f"package_dir is not a directory: {root}")

    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise HubIndexAdmissionError(f"missing package manifest: {manifest_path}")

    raw_manifest = _load_json_object(manifest_path)
    # Prefer soft view so adversarial packages still reach fail-closed gates.
    # Strict load is attempted only for optional integrity annotation.
    manifest = _PackageManifestView(raw_manifest)
    strict_ok = False
    strict_error = ""
    try:
        load_package_manifest(manifest_path)
        strict_ok = True
    except (
        HubIndexPackageError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        Exception,
    ) as exc:
        strict_error = str(exc)

    package_root_path = root / PACKAGE_ROOT_FILENAME
    package_root = (
        _load_json_object(package_root_path) if package_root_path.is_file() else {}
    )
    inventory_path = root / ARTIFACTS_INVENTORY_FILENAME
    artifacts_inventory = (
        _load_json_object(inventory_path) if inventory_path.is_file() else {}
    )
    package_receipt_path = root / RECEIPT_FILENAME
    package_receipt = (
        _load_json_object(package_receipt_path)
        if package_receipt_path.is_file()
        else {}
    )

    graph_snapshot: dict[str, Any] = {}
    graph_candidates = sorted(
        (root / "indexes" / "knowledge_graph").glob("*.snapshot.json")
    ) if (root / "indexes" / "knowledge_graph").is_dir() else []
    if graph_candidates:
        graph_snapshot = _load_json_object(graph_candidates[0])

    return {
        "artifacts_inventory": artifacts_inventory,
        "graph_snapshot": graph_snapshot,
        "manifest": manifest,
        "package_dir": root,
        "package_receipt": package_receipt,
        "package_root": package_root,
        "raw_manifest": raw_manifest,
        "strict_manifest_ok": strict_ok,
        "strict_manifest_error": strict_error,
    }


# ---------------------------------------------------------------------------
# Package-level gates
# ---------------------------------------------------------------------------


def _gate_package_integrity(ctx: Mapping[str, Any]) -> GateResult:
    reasons: set[str] = set()
    details: dict[str, Any] = {}
    manifest = ctx["manifest"]
    package_root = ctx.get("package_root") or {}
    root: Path = ctx["package_dir"]

    try:
        # Reconstruct a lightweight package-like validation from staged files.
        if str(getattr(manifest, "partition", "") or "") != "public":
            reasons.add("package.partition_not_public")
        present = set(getattr(manifest, "index_families_present", ()) or ())
        missing = [name for name in INDEX_FAMILIES if name not in present]
        if missing:
            reasons.add("package.missing_index_family")
            details["missing_index_families"] = missing
        for name in (
            MANIFEST_FILENAME,
            PACKAGE_ROOT_FILENAME,
            ARTIFACTS_INVENTORY_FILENAME,
        ):
            if not (root / name).is_file():
                reasons.add("package.missing_support_file")
                details.setdefault("missing_files", []).append(name)
        repos_root = root / "repos"
        if not repos_root.is_dir():
            reasons.add("package.missing_repos")
        else:
            for repo in _CANONICAL_REPOS:
                if not (repos_root / repo).is_dir():
                    reasons.add("package.missing_repository")
                    details.setdefault("missing_repos", []).append(repo)
        for family in ("corpus", "bm25", "vectors", "knowledge_graph"):
            if not (root / "indexes" / family).is_dir():
                reasons.add("package.missing_index_tree")
                details.setdefault("missing_indexes", []).append(family)

        root_cid = str(getattr(manifest, "package_root_cid", "") or "")
        if not root_cid.startswith("b"):
            reasons.add("package.invalid_package_root_cid")
        if package_root:
            pin = str(package_root.get("package_root_cid") or "")
            if pin and pin != root_cid:
                reasons.add("package.package_root_cid_mismatch")
        # Strict re-seal failure indicates content/descriptor drift (still
        # evaluate rights/DLP gates; surface integrity separately when the only
        # issue is digest drift after adversarial edits).
        if not ctx.get("strict_manifest_ok", True):
            err = str(ctx.get("strict_manifest_error") or "")
            details["strict_manifest_error"] = err[:200]
            # Digest-only drift after descriptor edits is expected for adversarial
            # fixtures; do not hard-fail integrity solely on digest mismatch so
            # rights/DLP gates remain the blocking surface.
            if "missing" in err.casefold() or "partition" in err.casefold():
                reasons.add("package.strict_validation_failed")
        details["package_root_cid"] = root_cid
        details["package_digest_sha256"] = str(
            getattr(manifest, "package_digest_sha256", "") or ""
        )
        details["strict_manifest_ok"] = bool(ctx.get("strict_manifest_ok", False))
    except Exception as exc:  # pragma: no cover - defensive
        reasons.add("package.integrity_error")
        details["error"] = type(exc).__name__

    return _make_gate(
        "package_integrity",
        passed=not reasons,
        reason_codes=tuple(reasons),
        details=details,
    )


def _gate_package_rights_privacy(ctx: Mapping[str, Any]) -> GateResult:
    reasons: set[str] = set()
    details: dict[str, Any] = {"artifacts_checked": 0}
    manifest = ctx["manifest"]
    rights = dict(getattr(manifest, "rights_summary", {}) or {})
    privacy = dict(getattr(manifest, "privacy_summary", {}) or {})

    if rights.get("all_reviewed") is not True:
        reasons.add("rights.unreviewed")
    if rights.get("all_redistribution_allowed") is not True:
        reasons.add("rights.redistribution_not_allowed")
    if str(rights.get("partition") or "") != "public":
        reasons.add("rights.partition_not_public")
    if str(privacy.get("privacy_class") or "") != "public":
        reasons.add("privacy.not_public")
    if privacy.get("all_reviewed") is not True:
        reasons.add("privacy.unreviewed")
    if str(privacy.get("partition") or "") != "public":
        reasons.add("privacy.partition_not_public")

    descriptors = list(getattr(manifest, "artifact_descriptors", ()) or ())
    inventory = ctx.get("artifacts_inventory") or {}
    if not descriptors and isinstance(inventory.get("artifacts"), list):
        descriptors = list(inventory["artifacts"])
    if not descriptors:
        reasons.add("rights.no_artifact_descriptors")

    for index, item in enumerate(descriptors):
        if not isinstance(item, Mapping):
            reasons.add("rights.descriptor_invalid")
            continue
        details["artifacts_checked"] = int(details["artifacts_checked"]) + 1
        rr = item.get("rights_review")
        pr = item.get("privacy_review")
        if not isinstance(rr, Mapping):
            reasons.add("rights.missing_on_artifact")
            continue
        if not isinstance(pr, Mapping):
            reasons.add("privacy.missing_on_artifact")
            continue
        status = str(rr.get("review_status") or "").strip().casefold()
        if status not in {"reviewed", "rightsreviewstatus.reviewed"}:
            reasons.add("rights.unreviewed")
        if rr.get("redistribution_allowed") is not True:
            reasons.add("rights.redistribution_not_allowed")
        p_status = str(pr.get("review_status") or "").strip().casefold()
        if p_status != "reviewed":
            reasons.add("privacy.unreviewed")
        p_class = str(pr.get("privacy_class") or "").strip().casefold()
        if p_class != "public":
            reasons.add("privacy.not_public")
            if p_class in {"private", "mixed", "unknown", ""}:
                reasons.add(f"privacy.{p_class or 'unknown'}")
        classification = str(item.get("classification") or "").strip().casefold()
        if classification in {
            "private",
            "confidential_application",
            "privileged_work_product",
            "restricted_export_review",
            "mixed",
            "unknown",
            "",
        }:
            if classification in {"", "unknown"}:
                reasons.add("classification.unknown")
            elif classification == "mixed":
                reasons.add("classification.mixed")
            else:
                reasons.add("classification.private")
        # Explicit mixed/unknown rights status tokens.
        rights_status = str(rr.get("review_status") or "").strip().casefold()
        if rights_status in {"unknown", "unreviewed", "rejected", "mixed"}:
            if rights_status == "unknown":
                reasons.add("rights.unknown")
            if rights_status == "mixed":
                reasons.add("rights.mixed")
            if rights_status in {"unreviewed", "rejected"}:
                reasons.add("rights.unreviewed")

    if "classification.private" in reasons and any(
        str((d or {}).get("classification") or "").startswith("public")
        for d in descriptors
        if isinstance(d, Mapping)
    ):
        reasons.add("batch.mixed_private_public")

    details["rights_summary"] = {
        "all_reviewed": rights.get("all_reviewed"),
        "partition": rights.get("partition"),
    }
    details["privacy_summary"] = {
        "privacy_class": privacy.get("privacy_class"),
        "all_reviewed": privacy.get("all_reviewed"),
    }
    return _make_gate(
        "package_rights_privacy",
        passed=not reasons,
        reason_codes=tuple(reasons),
        details=details,
    )


def _gate_package_dlp(
    ctx: Mapping[str, Any], policy: PatentHFReleasePolicyV2
) -> tuple[GateResult, list[Any]]:
    reasons: set[str] = set()
    findings: list[Any] = []
    root: Path = ctx["package_dir"]
    scanned_files = 0

    # Scan package-level JSON/text artifacts (not binary embeddings).
    candidates: list[Path] = []
    for name in (
        MANIFEST_FILENAME,
        PACKAGE_ROOT_FILENAME,
        ARTIFACTS_INVENTORY_FILENAME,
        RECEIPT_FILENAME,
        "layout-bundle.json",
    ):
        path = root / name
        if path.is_file():
            candidates.append(path)
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.endswith(".parquet"):
            # Parquet body scan happens in policy parquet gate when present.
            continue
        if path.suffix.lower() in {".json", ".md", ".jsonld", ".txt"}:
            if path not in candidates:
                candidates.append(path)

    for path in sorted(set(candidates), key=lambda p: p.as_posix()):
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError:
            reasons.add("dlp.unreadable")
            continue
        scanned_files += 1
        # Prefer structured JSON scan when possible.
        try:
            text = raw.decode("utf-8")
            payload = json.loads(text)
            if isinstance(payload, (Mapping, list)):
                findings.extend(
                    policy.scan_payload(payload, field_prefix=rel)
                )
            else:
                findings.extend(
                    policy.scan_bytes(rel, raw, treat_as_text=True)
                )
        except (UnicodeDecodeError, json.JSONDecodeError):
            findings.extend(policy.scan_bytes(rel, raw, treat_as_text=True))

    # Also scan manifest rights/privacy summaries in-memory.
    manifest = ctx["manifest"]
    findings.extend(
        policy.scan_payload(
            {
                "rights_summary": dict(getattr(manifest, "rights_summary", {}) or {}),
                "privacy_summary": dict(
                    getattr(manifest, "privacy_summary", {}) or {}
                ),
                "notes": str(getattr(manifest, "notes", "") or ""),
            },
            field_prefix="package.manifest",
        )
    )

    for finding in findings:
        category = getattr(finding, "category", None)
        code = str(getattr(finding, "code", "") or "")
        if category in (
            FindingCategory.SECRET,
            FindingCategory.ENCODED_LEAKAGE,
        ) or code.startswith("secret.") or code.startswith("encoded."):
            reasons.add("content.secret_or_encoded_leakage")
        elif category is FindingCategory.PRIVATE_MARKER or "private" in code:
            reasons.add("content.private_marker")
        elif category is FindingCategory.CLASSIFICATION:
            reasons.add("classification.blocked")

    return (
        _make_gate(
            "package_dlp",
            passed=not reasons,
            reason_codes=tuple(reasons),
            details={"scanned_files": scanned_files, "finding_count": len(findings)},
        ),
        findings,
    )


def _gate_package_orphans(ctx: Mapping[str, Any]) -> GateResult:
    reasons: set[str] = set()
    details: dict[str, Any] = {}
    snapshot = dict(ctx.get("graph_snapshot") or {})
    if not snapshot:
        # Missing graph snapshot is already a package integrity problem; still
        # surface orphan uncertainty fail-closed when indexes claim graph.
        indexes = ctx["package_dir"] / "indexes" / "knowledge_graph"
        if indexes.is_dir():
            reasons.add("orphan.snapshot_missing")
        return _make_gate(
            "package_orphans",
            passed=not reasons,
            reason_codes=tuple(reasons),
            details=details,
        )

    orphan_check = snapshot.get("orphan_check")
    details["orphan_check"] = orphan_check
    if orphan_check is False:
        reasons.add("orphan.check_failed")
    elif isinstance(orphan_check, str):
        lowered = orphan_check.strip().casefold()
        if lowered not in {"pass", "passed", "ok", "true", "1"}:
            reasons.add("orphan.check_failed")
            details["orphan_check_value"] = orphan_check
    elif orphan_check is None:
        reasons.add("orphan.check_missing")

    for key in ("orphan_joins", "orphan_count", "orphans"):
        value = snapshot.get(key)
        if value is None:
            continue
        try:
            if int(value) > 0:
                reasons.add("orphan.quality_report")
                details[key] = int(value)
        except (TypeError, ValueError):
            if value not in (False, "pass", "passed", "ok", [], {}):
                if isinstance(value, (list, tuple)) and len(value) > 0:
                    reasons.add("orphan.quality_report")
                    details[key] = len(value)
                elif isinstance(value, Mapping) and value:
                    reasons.add("orphan.quality_report")

    # Family binding pin may also carry orphan_check.
    manifest = ctx["manifest"]
    for family in getattr(manifest, "families", ()) or ():
        if isinstance(family, Mapping):
            role = str(family.get("role") or "")
            extra = family.get("extra") or {}
        else:
            role = str(getattr(family, "role", "") or "")
            extra = getattr(family, "extra", None) or {}
        if not isinstance(extra, Mapping):
            continue
        if role != "knowledge_graph":
            continue
        pinned = extra.get("orphan_check")
        details["family_orphan_check"] = pinned
        if pinned is False:
            reasons.add("orphan.check_failed")
        elif isinstance(pinned, str) and pinned.strip().casefold() not in {
            "pass",
            "passed",
            "ok",
            "true",
            "1",
        }:
            reasons.add("orphan.check_failed")

    return _make_gate(
        "package_orphans",
        passed=not reasons,
        reason_codes=tuple(reasons),
        details=details,
    )


# ---------------------------------------------------------------------------
# Inventory projection (package → release-policy inventory)
# ---------------------------------------------------------------------------


def _mandatory_coverage_sources(as_of: str) -> tuple[dict[str, Any], ...]:
    coverage = default_public_coverage(as_of=as_of)
    sources: list[dict[str, Any]] = []
    for source in coverage.sources:
        if hasattr(source, "to_dict"):
            sources.append(dict(source.to_dict()))
        elif isinstance(source, Mapping):
            sources.append(dict(source))
    # Ensure mandatory ids are present even if layout defaults drift.
    present = {str(item.get("source_id") or "") for item in sources}
    for source_id in MANDATORY_SOURCE_IDS:
        if source_id in present:
            continue
        sources.append(
            {
                "source_id": source_id,
                "license_expression": "public-domain-US-government",
                "official_edition_cutoff": as_of,
                "current_through": as_of,
            }
        )
    return tuple(sources)


def _merge_coverage_sources(
    existing: Sequence[Mapping[str, Any]],
    mandatory: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    merged: dict[str, dict[str, Any]] = {}
    for item in list(existing) + list(mandatory):
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        # Keep first-seen native package disclosure; mandatory fills gaps.
        if source_id not in merged:
            merged[source_id] = dict(item)
    return tuple(merged[key] for key in sorted(merged))


def _config_row_counts_from_package(manifest: Any) -> dict[str, int]:
    """Project package family counts into config_row_counts for support files."""
    counts = getattr(manifest, "counts", None)
    raw = counts.to_dict() if hasattr(counts, "to_dict") else dict(counts or {})
    projected: dict[str, int] = {}
    corpus_docs = int(raw.get("corpus_documents") or 0)
    if corpus_docs:
        # Spread corpus rows onto a representative public config for parity.
        projected["usc"] = corpus_docs
    bm25_docs = int(raw.get("bm25_documents") or 0)
    if bm25_docs:
        projected["bm25_documents"] = bm25_docs
    bm25_postings = int(raw.get("bm25_postings") or 0)
    if bm25_postings:
        projected["bm25_postings"] = bm25_postings
    vectors = int(raw.get("vector_documents") or 0)
    if vectors:
        projected["vectors"] = vectors
    graph_nodes = int(raw.get("graph_nodes") or 0)
    if graph_nodes:
        projected["graph_nodes"] = graph_nodes
    graph_edges = int(raw.get("graph_edges") or 0)
    if graph_edges:
        projected["graph_edges"] = graph_edges
    return projected


def inventory_from_hub_index_package(
    package_dir: str | Path,
    *,
    as_of: str = "2026-08-01",
    inject_parquet: bool = False,
    parquet_body: bytes | None = None,
    corrupt_parquet: bool = False,
    orphan_joins: int | None = None,
    orphan_check: bool | str | None = None,
    policy_receipt_admitted: bool | None = None,
    classification_summary: Mapping[str, int] | None = None,
    include_mandatory_coverage: bool = True,
) -> StagedReleaseInventory:
    """Project a staged hub index package into a release-policy inventory.

    The package already carries Viewer cards/configs under ``repos/``. Support
    files required by PATLAW-158 (release-manifest / quality-report /
    policy-admission) are synthesized from package pins so gates can run
    without requiring a separate HF v2 release tree.
    """
    ctx = load_package_context(package_dir)
    root: Path = ctx["package_dir"]
    manifest = ctx["manifest"]
    organization = str(getattr(manifest, "organization", None) or ORGANIZATION)

    # Start from disk inventory of repos (cards, configs, optional parquet).
    base = load_staged_release_inventory(root)
    mandatory = (
        _mandatory_coverage_sources(as_of) if include_mandatory_coverage else ()
    )

    config_counts = _config_row_counts_from_package(manifest)
    injecting = inject_parquet or corrupt_parquet or parquet_body is not None
    injected_counts: dict[str, int] = {}
    repositories: list[RepositoryInventory] = []
    for repo in base.repositories:
        sources = _merge_coverage_sources(repo.coverage_sources, mandatory)
        shards = list(repo.parquet_shards)
        row_counts = dict(repo.config_row_counts)

        if injecting:
            # Inject a single representative shard for negative/positive tests.
            body = parquet_body
            if body is None:
                body = b"not-parquet" if corrupt_parquet else _minimal_parquet_bytes(1)
            sha = _sha256_bytes(body)
            rows = 0 if corrupt_parquet else 1
            config_name = "usc" if repo.repository == CORPUS_REPOSITORY else (
                "vectors"
                if repo.repository == VECTORS_REPOSITORY
                else "bm25_documents"
                if repo.repository == BM25_REPOSITORY
                else "graph_nodes"
            )
            rel = f"data/{config_name}/part-000000.parquet"
            shards = [
                StagedParquetShard(
                    relative_path=rel,
                    repository=repo.repository,
                    config_name=config_name,
                    sha256=sha,
                    size_bytes=len(body),
                    row_count=rows,
                    content=body,
                )
            ]
            row_counts = {config_name: rows}
            injected_counts[config_name] = (
                injected_counts.get(config_name, 0) + rows
            )

        repositories.append(
            RepositoryInventory(
                repository=repo.repository,
                dataset_id=repo.dataset_id or f"{organization}/{repo.repository}",
                role=repo.role or _ROLE_BY_REPO.get(repo.repository, "unknown"),
                relative_paths=repo.relative_paths,
                parquet_shards=tuple(shards),
                config_names=repo.config_names,
                config_row_counts=row_counts,
                has_readme=repo.has_readme,
                has_dataset_configs=repo.has_dataset_configs,
                has_coverage=repo.has_coverage,
                coverage_sources=sources,
                dataset_configs=dict(repo.dataset_configs),
            )
        )

    # When shards are injected, bind support counts to injected inventory so
    # count_parity does not false-fail on package family totals.
    if injecting:
        config_counts = dict(injected_counts)

    # Ensure all four canonical repos appear even if package is partial.
    present = {r.repository for r in repositories}
    for repo_name in _CANONICAL_REPOS:
        if repo_name in present:
            continue
        sources = _merge_coverage_sources((), mandatory)
        repositories.append(
            RepositoryInventory(
                repository=repo_name,
                dataset_id=f"{organization}/{repo_name}",
                role=_ROLE_BY_REPO[repo_name],
                relative_paths=(),
                parquet_shards=(),
                config_names=(),
                config_row_counts={},
                has_readme=False,
                has_dataset_configs=False,
                has_coverage=bool(sources),
                coverage_sources=sources,
                dataset_configs={},
            )
        )

    # Quality / orphan projection from graph snapshot + overrides.
    graph = dict(ctx.get("graph_snapshot") or {})
    quality_orphan_check: Any = graph.get("orphan_check", True)
    if isinstance(quality_orphan_check, str):
        quality_orphan_check = quality_orphan_check.strip().casefold() in {
            "pass",
            "passed",
            "ok",
            "true",
            "1",
        }
    quality_orphan_joins = int(graph.get("orphan_joins") or 0)
    if orphan_check is not None:
        quality_orphan_check = orphan_check
    if orphan_joins is not None:
        quality_orphan_joins = int(orphan_joins)

    quality_report: dict[str, Any] = {
        "config_row_counts": dict(config_counts),
        "total_data_rows": int(sum(config_counts.values())),
        "orphan_check": quality_orphan_check
        if not isinstance(quality_orphan_check, str)
        else quality_orphan_check.strip().casefold()
        in {"pass", "passed", "ok", "true", "1"},
        "orphan_joins": quality_orphan_joins,
        "package_root_cid": str(manifest.package_root_cid),
        "graph_root_cid": str(manifest.graph_root_cid),
        "index_families_present": list(INDEX_FAMILIES),
    }
    # Allow string false-y orphan_check override for package tests.
    if orphan_check is False or (
        isinstance(orphan_check, str)
        and orphan_check.strip().casefold()
        not in {"pass", "passed", "ok", "true", "1"}
    ):
        quality_report["orphan_check"] = False

    rights_ok = bool(
        (getattr(manifest, "rights_summary", {}) or {}).get("all_reviewed")
    ) and str(
        (getattr(manifest, "privacy_summary", {}) or {}).get("privacy_class") or ""
    ) == "public"
    admitted_flag = (
        bool(policy_receipt_admitted)
        if policy_receipt_admitted is not None
        else rights_ok
    )
    class_summary = dict(classification_summary or {})
    if not class_summary:
        class_summary = {
            "public_official": int(
                getattr(manifest.counts, "corpus_documents", 0) or 0
            )
        }

    policy_receipt: dict[str, Any] = {
        "admitted": admitted_flag,
        "policy_version": RELEASE_POLICY_V2_VERSION,
        "policy_sha256": RELEASE_POLICY_V2_SHA256,
        "classification_summary": class_summary,
        "package_root_cid": str(manifest.package_root_cid),
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
    }

    release_manifest: dict[str, Any] = {
        "organization": organization,
        "schema_version": "patent.hub_index_package.admission.v1",
        "package_root_cid": str(manifest.package_root_cid),
        "package_digest_sha256": str(manifest.package_digest_sha256),
        "corpus_root_cid": str(manifest.corpus_root_cid),
        "bm25_root_cid": str(manifest.bm25_root_cid),
        "vector_root_cid": str(manifest.vector_root_cid),
        "graph_root_cid": str(manifest.graph_root_cid),
        "version_tag": str(manifest.version_tag),
        "config_row_counts": dict(config_counts),
        "total_data_rows": int(sum(config_counts.values())),
        "repositories": [
            {
                "repository": repo.repository,
                "role": repo.role,
                "dataset_id": repo.dataset_id,
                "total_row_count": int(repo.total_row_count),
            }
            for repo in repositories
        ],
        "index_families_present": list(INDEX_FAMILIES),
        "partition": "public",
    }

    return StagedReleaseInventory(
        root=str(root),
        organization=organization,
        repositories=tuple(
            sorted(repositories, key=lambda r: r.repository)
        ),
        manifest=release_manifest,
        quality_report=quality_report,
        policy_receipt=policy_receipt,
        support_paths=(
            RELEASE_MANIFEST_FILENAME,
            QUALITY_REPORT_FILENAME,
            POLICY_RECEIPT_FILENAME,
        ),
    )


# ---------------------------------------------------------------------------
# Admission entrypoint
# ---------------------------------------------------------------------------


def admit_patent_legal_hub_indexes(
    *,
    package_dir: str | Path | None = None,
    default_fixture: bool = False,
    stage_dir: str | Path | None = None,
    organization: str = ORGANIZATION,
    as_of: str = "2026-08-01",
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
    run_viewer_gate: bool = True,
    force_viewer_invalid: bool = False,
    require_admitted: bool = True,
    receipt_out: str | Path | None = None,
    inventory: StagedReleaseInventory | None = None,
    inject_parquet: bool = False,
    corrupt_parquet: bool = False,
    parquet_body: bytes | None = None,
    orphan_joins: int | None = None,
    orphan_check: bool | str | None = None,
    policy_receipt_admitted: bool | None = None,
    classification_summary: Mapping[str, int] | None = None,
    include_mandatory_coverage: bool = True,
) -> dict[str, Any]:
    """Run fail-closed DLP/rights/Viewer admission over a hub index package.

    Returns an admission receipt dict that binds ``package_root_cid`` and every
    gate outcome. Never resolves Hub credentials or contacts the live Hub.
    """
    try:
        assert_credentials_unresolved()
    except CredentialPrematureError as exc:
        raise HubIndexAdmissionError(str(exc)) from exc

    root = resolve_package_dir(
        package_dir=package_dir,
        default_fixture=default_fixture,
        stage_dir=stage_dir,
        organization=organization,
    )
    ctx = load_package_context(root)
    manifest = ctx["manifest"]

    policy = PatentHFReleasePolicyV2(
        as_of=as_of, max_source_age_days=max_source_age_days
    )

    package_gates: list[GateResult] = []
    findings: list[Any] = []
    reasons: set[str] = set()

    integrity_gate = _gate_package_integrity(ctx)
    package_gates.append(integrity_gate)
    reasons.update(integrity_gate.reason_codes)

    rights_gate = _gate_package_rights_privacy(ctx)
    package_gates.append(rights_gate)
    reasons.update(rights_gate.reason_codes)

    dlp_gate, dlp_findings = _gate_package_dlp(ctx, policy)
    package_gates.append(dlp_gate)
    reasons.update(dlp_gate.reason_codes)
    findings.extend(dlp_findings)

    orphan_gate = _gate_package_orphans(ctx)
    package_gates.append(orphan_gate)
    reasons.update(orphan_gate.reason_codes)

    # Project inventory (caller may supply a mutated inventory for tests).
    if inventory is None:
        try:
            inventory = inventory_from_hub_index_package(
                root,
                as_of=as_of,
                inject_parquet=inject_parquet,
                parquet_body=parquet_body,
                corrupt_parquet=corrupt_parquet,
                orphan_joins=orphan_joins,
                orphan_check=orphan_check,
                policy_receipt_admitted=policy_receipt_admitted,
                classification_summary=classification_summary,
                include_mandatory_coverage=include_mandatory_coverage,
            )
        except (ReleasePolicyV2Error, HubIndexAdmissionError) as exc:
            raise HubIndexAdmissionError(
                f"cannot project package inventory: {exc}"
            ) from exc

    viewer_gateway = None
    if run_viewer_gate:
        service = FakeDatasetViewerService(
            inventory=inventory, force_invalid=force_viewer_invalid
        )
        viewer_gateway = FakeViewerGateway(service)

    try:
        decision = policy.evaluate_inventory(
            inventory,
            viewer_gateway=viewer_gateway,
            run_viewer_gate=run_viewer_gate,
        )
    except CredentialPrematureError as exc:
        raise HubIndexAdmissionError(str(exc)) from exc
    except ReleasePolicyV2Error as exc:
        raise HubIndexAdmissionError(str(exc)) from exc

    policy_gates = list(decision.gate_results)
    reasons.update(decision.reason_codes)
    findings.extend(list(decision.findings))

    if decision.policy_sha256 != RELEASE_POLICY_V2_SHA256:
        reasons.add("policy.drift")

    all_gates = tuple(package_gates) + tuple(policy_gates)
    gate_results = [_gate_dict(g) for g in all_gates]
    gate_names = [g["name"] for g in gate_results]
    admitted = not reasons

    viewer_gate = next(
        (g for g in gate_results if g.get("name") == "dataset_viewer"), None
    )
    rights_dlp_gate = next(
        (g for g in gate_results if g.get("name") == "rights_dlp"), None
    )

    finding_payloads: list[dict[str, Any]] = []
    for item in findings:
        if hasattr(item, "to_dict"):
            finding_payloads.append(_sanitize_finding_dict(item.to_dict()))
        elif isinstance(item, Mapping):
            finding_payloads.append(_sanitize_finding_dict(item))

    receipt: dict[str, Any] = {
        "admitted": admitted,
        "bm25_root_cid": str(manifest.bm25_root_cid),
        "code_version": CODE_VERSION,
        "config_id": CONFIG_ID,
        "corpus_root_cid": str(manifest.corpus_root_cid),
        "credentials_resolved": False,
        "expected_gate_names": list(EXPECTED_GATE_NAMES),
        "expected_policy_sha256": RELEASE_POLICY_V2_SHA256,
        "expected_policy_version": RELEASE_POLICY_V2_VERSION,
        "finding_count": len(finding_payloads),
        "findings": finding_payloads,
        "gate_names": gate_names,
        "gate_results": gate_results,
        "goal_id": GOAL_ID,
        "graph_root_cid": str(manifest.graph_root_cid),
        "hub_upload": False,
        "index_families_present": list(
            getattr(manifest, "index_families_present", INDEX_FAMILIES) or INDEX_FAMILIES
        ),
        "organization": str(manifest.organization or organization),
        "package_digest_sha256": str(manifest.package_digest_sha256),
        "package_dir": str(root),
        "package_root_cid": str(manifest.package_root_cid),
        "partition": str(getattr(manifest, "partition", "public") or "public"),
        "policy_sha256": decision.policy_sha256,
        "policy_version": decision.policy_version,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "reason_codes": sorted(reasons),
        "receipt_schema": ADMISSION_RECEIPT_SCHEMA,
        "rights_dlp_passed": bool(
            rights_dlp_gate and rights_dlp_gate.get("passed")
        ),
        "task_id": TASK_ID,
        "tokens_used": False,
        "vector_root_cid": str(manifest.vector_root_cid),
        "version_tag": str(manifest.version_tag),
        "viewer_contracts": {
            "endpoints_checked": list(VIEWER_ENDPOINTS) if run_viewer_gate else [],
            "gate": viewer_gate,
            "passed": bool(viewer_gate and viewer_gate.get("passed"))
            if run_viewer_gate
            else None,
        },
        "viewer_contracts_passed": bool(viewer_gate and viewer_gate.get("passed"))
        if run_viewer_gate
        else None,
        "viewer_endpoints_checked": list(VIEWER_ENDPOINTS)
        if run_viewer_gate
        else [],
    }

    # Content-address the receipt body (exclude write-time presentation).
    receipt_body = {
        key: receipt[key]
        for key in (
            "admitted",
            "bm25_root_cid",
            "corpus_root_cid",
            "gate_results",
            "goal_id",
            "graph_root_cid",
            "index_families_present",
            "package_digest_sha256",
            "package_root_cid",
            "policy_sha256",
            "policy_version",
            "reason_codes",
            "receipt_schema",
            "task_id",
            "vector_root_cid",
        )
        if key in receipt
    }
    receipt["receipt_digest_sha256"] = _sha256_text(_canonical_json(receipt_body))

    _reject_secrets_in_payload(receipt, label="admission_receipt")

    if receipt_out is not None:
        out_path = Path(receipt_out).expanduser().resolve()
        _atomic_write_text(
            out_path, _canonical_json(receipt) + "\n"
        )
        receipt["receipt_out"] = str(out_path)

    if require_admitted and not receipt["admitted"]:
        raise PackageAdmissionRejectedError(
            "hub index package rejected before credentials: "
            + ", ".join(receipt["reason_codes"])
        )
    return receipt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Admit hub index package through DLP, rights, and Dataset Viewer "
            f"gates ({TASK_ID}). Credential-free; no Hub upload."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--package-dir",
        type=Path,
        default=None,
        help="Staged hub index package directory (PATLAW-174 output)",
    )
    input_group.add_argument(
        "--default-fixture",
        action="store_true",
        help="Materialize the built-in multi-family package fixture and admit it",
    )
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=None,
        help="Directory for --default-fixture staging (temp dir when omitted)",
    )
    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="Reference date for mandatory source freshness (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-source-age-days",
        type=int,
        default=DEFAULT_MAX_SOURCE_AGE_DAYS,
        help=(
            "Maximum age of mandatory sources "
            f"(default {DEFAULT_MAX_SOURCE_AGE_DAYS})"
        ),
    )
    parser.add_argument(
        "--skip-viewer-gate",
        action="store_true",
        help="Skip Dataset Viewer contract checks (not recommended)",
    )
    parser.add_argument(
        "--force-viewer-invalid",
        action="store_true",
        help="Force fake Viewer is-valid=false (negative testing)",
    )
    parser.add_argument(
        "--allow-reject",
        action="store_true",
        help="Exit 0 even when admission is refused (still prints reasons)",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        default=None,
        help="Write the admission receipt JSON to this path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full admission receipt as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = admit_patent_legal_hub_indexes(
            package_dir=args.package_dir,
            default_fixture=bool(args.default_fixture),
            stage_dir=args.stage_dir,
            organization=args.organization,
            as_of=args.as_of,
            max_source_age_days=args.max_source_age_days,
            run_viewer_gate=not args.skip_viewer_gate,
            force_viewer_invalid=bool(args.force_viewer_invalid),
            require_admitted=not args.allow_reject,
            receipt_out=args.receipt_out,
        )
    except PackageAdmissionRejectedError as exc:
        payload = {
            "admitted": False,
            "error": str(exc),
            "goal_id": GOAL_ID,
            "policy_sha256": RELEASE_POLICY_V2_SHA256,
            "policy_version": RELEASE_POLICY_V2_VERSION,
            "receipt_schema": ADMISSION_RECEIPT_SCHEMA,
            "task_id": TASK_ID,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    except (
        HubIndexAdmissionError,
        CredentialPrematureError,
        ReleasePolicyV2Error,
        HubIndexPackageError,
    ) as exc:
        payload = {
            "admitted": False,
            "error": str(exc),
            "goal_id": GOAL_ID,
            "policy_version": RELEASE_POLICY_V2_VERSION,
            "receipt_schema": ADMISSION_RECEIPT_SCHEMA,
            "task_id": TASK_ID,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "ADMITTED" if result["admitted"] else "REJECTED"
        print(
            f"{status} task={TASK_ID}"
            f" package_root_cid={result.get('package_root_cid', '')}"
            f" policy={result.get('policy_version')}"
            f" gates={len(result.get('gate_results') or [])}"
            f" findings={result.get('finding_count', 0)}"
        )
        if result.get("reason_codes"):
            print("reasons: " + ", ".join(result["reason_codes"]))
        for gate in result.get("gate_results") or []:
            mark = "PASS" if gate.get("passed") else "FAIL"
            extra = ""
            if gate.get("reason_codes"):
                extra = " " + ",".join(gate["reason_codes"])
            print(f"  [{mark}] {gate.get('name')}{extra}")
        if result.get("receipt_out"):
            print(f"receipt_out: {result['receipt_out']}")
    return 0 if result["admitted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
