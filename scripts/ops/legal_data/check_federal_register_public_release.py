#!/usr/bin/env python3
"""Verify the immutable Federal Register public revision end to end (LCR-066).

Read-only verifier against the recorded Federal Register public SHA on
``justicedao/ipfs_federal_register``. This script never mutates the Hub,
never repairs remote state, and never treats a fixture-only substitute
as a public pin.

Default fixture mode is credential-free and does not contact the Hub:

1. Load the LCR-065 publication receipt (40-hex public SHA + exact
   manifest digest).
2. Reconstruct the proposed artifact tree in an isolated in-memory transport.
3. Compare public artifacts to the staged candidate.
4. Verify the default Dataset Viewer is coherent.
5. Reconcile every semantic family and full-text / admission disposition.
6. Run BM25 / vector / hybrid / graph / filter / cache canaries and
   keep sparse I/O inside declared budgets.

The fixture loop tests byte/parity mechanics only and is never accepted as
evidence of a public release. ``--require-public-pin`` validates a separately
sealed, read-only live canary bound to the recorded immutable public SHA.
Combined with ``--check`` it is the official validation gate::

    python scripts/ops/legal_data/check_federal_register_public_release.py \\
        --require-public-pin --check

Opt-in remote Hub redownload requires explicit ``--repo-id`` + immutable
40-hex ``--revision`` and never infers ``main`` / ``latest``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.federal_register_sparse_query import (  # noqa: E402
    QUERY_MODES,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (  # noqa: E402
    FEDERAL_DATASET_REPO_ID,
    PublicationGateError,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MutableRevisionError,
    ResolverError,
    validate_immutable_revision,
    validate_repo_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
)
from scripts.ops.legal_data.canary_federal_register_hf_release import (  # noqa: E402
    CANARY_QUERY_SPECS,
    CONTROL_INDEXES,
    DEFAULT_BUDGETS,
    CanaryBudgetError,
    CanaryParityError,
    check_fulltext_key_family_parity,
    compare_cutoff_inventory,
    compare_staged_to_candidate,
    load_fulltext_coverage,
    run_bounded_canary_traces,
    verify_viewer_configs,
)
from scripts.ops.legal_data.publish_federal_register_hf_release import (  # noqa: E402
    DEFAULT_DATASET_REPO,
    DEFAULT_RECEIPT_RELPATH,
    DEFAULT_STAGING_BRANCH,
    FORBIDDEN_OPERATIONS,
    PRODUCTION_REVISION,
    PUBLIC_BRANCH,
    SECRET_ENV_NAMES,
    FakeFederalRegisterPublicHub,
    PublishFederalRegisterError,
    PublishSafetyError,
    check_publication_receipt,
    load_candidate_report,
    plan_public_from_candidate,
    reject_credentials_in_payload,
    reject_secrets_in_argv,
    release_file_bytes,
    require_immutable_revision,
)
from scripts.ops.legal_data.stage_federal_register_hf_release import (  # noqa: E402
    StageFederalRegisterError,
    StageSafetyError,
    build_fixture_release,
    load_cutoff_inventory,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-066"
GOAL_ID: Final = "LCR-G140"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
if DEFAULT_DATASET_REPO != "justicedao/ipfs_federal_register":
    raise RuntimeError(
        "sealed Federal Register target drifted from the publication gate"
    )
PRODUCER: Final = "check_federal_register_public_release.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-065",)
PUBLICATION_TASK_ID: Final = "LCR-065"
STAGING_CANARY_TASK_ID: Final = "LCR-064"

CANARY_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-public-canary@1"
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_public_canary.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
DEFAULT_INVENTORY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)
DEFAULT_ADMISSION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_admission.json"
)
DEFAULT_FULLTEXT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json"
)
DEFAULT_STAGING_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_staging_canary.json"
)
DEFAULT_EVALUATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.json"
)
DEFAULT_QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_query_contract.json"
)

REMOTE_REPO_ENV: Final = "FEDERAL_REGISTER_PUBLIC_CANARY_REPO_ID"
REMOTE_REVISION_ENV: Final = "FEDERAL_REGISTER_PUBLIC_CANARY_REVISION"
REMOTE_ENABLE_ENV: Final = "FEDERAL_REGISTER_PUBLIC_CANARY_REMOTE"

PUBLIC_QUERY_SPECS: Final = CANARY_QUERY_SPECS
PUBLIC_BUDGETS: Final = dict(DEFAULT_BUDGETS)

SELF_DIGEST_FIELDS: Final = frozenset(
    {"canonical_digest", "content_digest", "digest", "report_digest"}
)

MAX_REPORT_BYTES: Final = 1048576

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CheckFederalRegisterPublicError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublicBudgetError(CheckFederalRegisterPublicError, CanaryBudgetError):
    """Raised when redownload or query budgets are exceeded."""


class PublicParityError(CheckFederalRegisterPublicError, CanaryParityError):
    """Raised when public artifacts drift from the staged candidate."""


class PublicPinError(CheckFederalRegisterPublicError):
    """Raised when a fixture canary is substituted for the recorded public pin."""


class PublicRemoteError(CheckFederalRegisterPublicError):
    """Raised when remote coordinates are missing or mutable."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_admission_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_ADMISSION_RELPATH).resolve()


def default_staging_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_STAGING_CANARY_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise CheckFederalRegisterPublicError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckFederalRegisterPublicError(
            f"cannot read JSON {target.name}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CheckFederalRegisterPublicError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    body = {
        key: value
        for key, value in payload.items()
        if key not in SELF_DIGEST_FIELDS
    }
    return (json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def seal_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    digest = hashlib.sha256(_canonical_report_bytes(report)).hexdigest()
    report["content_digest"] = digest
    report["digest"] = digest
    reject_credentials_in_payload(report, label="federal_public_canary")
    return report


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise CheckFederalRegisterPublicError(
            f"report exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_canary_report(
    report: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    sealed = seal_report(report)
    target = Path(path) if path is not None else default_report_path(repo_root)
    if sealed.get("fixture_only") is True and target.resolve() == default_report_path(
        repo_root
    ):
        raise PublicPinError(
            "refusing to replace canonical public evidence with a fixture canary"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ---------------------------------------------------------------------------
# Publication receipt / public pin
# ---------------------------------------------------------------------------


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load the LCR-065 receipt and require a 40-hex public SHA + digest."""

    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_receipt_path(repo_root)
    )
    receipt = load_json_mapping(target)
    if str(receipt.get("task_id") or "") != PUBLICATION_TASK_ID:
        raise PublicPinError(
            f"publication receipt task_id is {receipt.get('task_id')!r}, "
            f"expected {PUBLICATION_TASK_ID!r}"
        )
    if str(receipt.get("schema") or "") != (
        "ipfs_datasets_py/legal-corpora-reindex-federal-publication-receipt@1"
    ):
        raise PublicPinError(
            f"publication receipt schema is {receipt.get('schema')!r}"
        )
    pin = require_public_pin(receipt)
    manifest = str(receipt.get("manifest_digest") or receipt.get("final_manifest_digest") or "")
    if not _SHA256_RE.fullmatch(manifest):
        raise PublicPinError(
            "publication receipt must bind an exact 64-hex manifest digest"
        )
    old = require_immutable_revision(receipt.get("old_sha"), name="old_sha")
    staging = require_immutable_revision(receipt.get("staging_sha"), name="staging_sha")
    if old != PRODUCTION_REVISION:
        raise PublicPinError(
            f"receipt old SHA must remain the sealed previous public pin "
            f"{PRODUCTION_REVISION}"
        )
    if pin == old:
        raise PublicPinError("public SHA must differ from the previous public pin")
    if pin == staging:
        raise PublicPinError("public SHA must differ from the staging SHA")
    repo = str(receipt.get("target_repo") or receipt.get("dataset_repo_id") or "")
    if repo != DEFAULT_DATASET_REPO:
        raise PublicPinError(
            f"receipt target must be {DEFAULT_DATASET_REPO!r}, got {repo!r}"
        )
    reject_credentials_in_payload(receipt, label="federal_publication_receipt")
    return receipt


def require_public_pin(payload: Mapping[str, Any], *, name: str = "public_sha") -> str:
    """Require an immutable 40-hex public pin on a receipt or canary."""

    raw = payload.get("public_sha") or payload.get("public_revision")
    if raw in (None, ""):
        raise PublicPinError(f"{name} is missing from the publication receipt/canary")
    pin = require_immutable_revision(raw, name=name)
    if not _GIT_SHA_RE.fullmatch(pin):
        raise PublicPinError(f"{name} must be an immutable 40-hex SHA, got {raw!r}")
    if pin in {"main", "latest", "HEAD"} or pin.lower() in {"main", "latest", "head"}:
        raise PublicPinError(f"{name} must not be a mutable revision")
    return pin


def load_admission_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_admission_path(repo_root)
    )
    if not target.is_file():
        raise CheckFederalRegisterPublicError(
            f"admission report not found: {DEFAULT_ADMISSION_RELPATH.as_posix()}"
        )
    return load_json_mapping(target)


def load_staging_canary_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_staging_canary_path(repo_root)
    )
    if not target.is_file():
        raise CheckFederalRegisterPublicError(
            f"staging canary not found: {DEFAULT_STAGING_CANARY_RELPATH.as_posix()}"
        )
    return load_json_mapping(target)


# ---------------------------------------------------------------------------
# Viewer / parity / traces
# ---------------------------------------------------------------------------


def compare_public_to_candidate(
    public: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Require every candidate descriptor to reappear on the public revision."""

    try:
        compared = compare_staged_to_candidate(public, candidate)
    except CanaryParityError as exc:
        raise PublicParityError(
            "public artifacts drifted from staged candidate: " + str(exc)
        ) from exc
    compared["public_equals_staged_candidate"] = True
    return compared


def compare_public_to_receipt(
    public_files: Mapping[str, bytes],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind reconstructed public bytes to the LCR-065 upload responses."""

    expected: dict[str, str] = {}
    for item in list(receipt.get("upload_responses") or receipt.get("uploaded") or []):
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("relative_path") or "")
        digest = str(item.get("sha256") or "")
        if not path or not digest:
            continue
        expected[path] = digest
    if not expected:
        raise PublicParityError("publication receipt has no uploaded artifacts to verify")
    mismatches: list[str] = []
    compared = 0
    for path, digest in sorted(expected.items()):
        blob = public_files.get(path)
        if blob is None:
            mismatches.append(f"missing:{path}")
            continue
        got = hashlib.sha256(blob).hexdigest()
        compared += 1
        if got != digest:
            mismatches.append(f"{path}:sha256")
    if mismatches:
        raise PublicParityError(
            "public redownload drifted from publication receipt: "
            + "; ".join(mismatches[:16])
        )
    return {
        "compared": compared,
        "exact_match": True,
        "mismatches": [],
        "ok": True,
        "public_sha": require_public_pin(receipt),
        "receipt_file_count": compared,
    }


def compare_cutoff_admission(
    candidate: Mapping[str, Any],
    inventory: Mapping[str, Any],
    admission: Mapping[str, Any],
    fulltext: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind public cutoff, inventory, and admission/full-text dispositions."""

    try:
        inventory_cmp = compare_cutoff_inventory(candidate, inventory)
    except CanaryParityError as exc:
        raise PublicParityError(str(exc)) from exc

    adm_acc = (
        admission.get("acceptance")
        if isinstance(admission.get("acceptance"), Mapping)
        else {}
    )
    adm_cutoff = str(
        admission.get("observation_cutoff")
        or adm_acc.get("observation_cutoff")
        or ""
    )
    if adm_cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise PublicParityError(
            f"admission observation_cutoff is {adm_cutoff!r}, "
            f"expected {DEFAULT_OBSERVATION_CUTOFF!r}"
        )
    failed = adm_acc.get("failed_final")
    if failed not in (None, 0):
        raise PublicParityError(f"admission has failed_final={failed}")
    if adm_acc.get("failed_final_zero") is False:
        raise PublicParityError("admission failed_final_zero is false")
    if adm_acc.get("one_disposition_per_input") is False:
        raise PublicParityError("admission is missing one-disposition-per-input")
    if adm_acc.get("admission_recovery_reconciled") is False:
        raise PublicParityError("admission recovery is not reconciled")

    ledger = (
        admission.get("admission_recovery_ledger")
        if isinstance(admission.get("admission_recovery_ledger"), Mapping)
        else {}
    )
    adm_disp = dict(ledger.get("coverage_dispositions") or {})
    ft_disp: dict[str, Any] = {}
    if fulltext:
        ft_disp = dict(fulltext.get("dispositions") or {})
        ft_cutoff = str(
            fulltext.get("observation_cutoff")
            or (fulltext.get("acceptance") or {}).get("observation_cutoff")
            or DEFAULT_OBSERVATION_CUTOFF
        )
        if ft_cutoff != DEFAULT_OBSERVATION_CUTOFF:
            raise PublicParityError(
                f"full-text coverage cutoff is {ft_cutoff!r}"
            )
        ft_failed = (fulltext.get("counts") or {}).get("failed_final")
        if ft_failed not in (None, 0):
            raise PublicParityError(f"full-text coverage has failed_final={ft_failed}")
    if adm_disp and ft_disp and adm_disp != ft_disp:
        raise PublicParityError(
            "admission coverage dispositions do not match full-text dispositions"
        )

    return {
        "admission_recovery_reconciled": True,
        "dataset_repo_id": FEDERAL_DATASET_REPO_ID,
        "dispositions": adm_disp or ft_disp,
        "failed_final": 0,
        "inventory": inventory_cmp,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "one_disposition_per_input": True,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
    }


def _public_descriptor_map(
    files: Mapping[str, bytes],
    plan_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    public: dict[str, dict[str, Any]] = {}
    plan_index = {
        str(item.get("relative_path")): dict(item)
        for item in plan_artifacts
        if isinstance(item, Mapping) and item.get("relative_path")
    }
    for path, blob in files.items():
        digest = hashlib.sha256(blob).hexdigest()
        planned = plan_index.get(path) or {}
        public[path] = {
            "content_cid": planned.get("content_cid"),
            "family": planned.get("family"),
            "first_key": planned.get("first_key"),
            "last_key": planned.get("last_key"),
            "relative_path": path,
            "row_count": planned.get("row_count"),
            "sha256": digest,
            "size_bytes": len(blob),
        }
        if planned.get("sha256") and planned["sha256"] != digest:
            raise PublicParityError(
                f"public bytes for {path} do not match the candidate/plan digest"
            )
    return public


def _descriptor_index(
    items: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    """Build a strict, traversal-safe descriptor index."""

    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise PublicParityError(f"{label} descriptor is not an object")
        path = str(item.get("relative_path") or "")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise PublicParityError(f"unsafe {label} descriptor path: {path!r}")
        if path in indexed:
            raise PublicParityError(f"duplicate {label} descriptor path: {path}")
        digest = str(item.get("sha256") or "")
        if not _SHA256_RE.fullmatch(digest):
            raise PublicParityError(
                f"{label} descriptor {path} is missing a 64-hex sha256"
            )
        size = item.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PublicParityError(
                f"{label} descriptor {path} has invalid size_bytes"
            )
        indexed[path] = dict(item)
    if not indexed:
        raise PublicParityError(f"{label} descriptor inventory is empty")
    return indexed


def reconstruct_public_revision(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    hub: FakeFederalRegisterPublicHub | None = None,
) -> dict[str, Any]:
    """Exercise public-tree byte mechanics in the isolated fixture transport.

    This function never proves that bytes exist on the public Hub.  It is
    deliberately useful only for tests and offline parity rehearsal.
    """

    release = build_fixture_release(repo_root=repo_root)
    plan = plan_public_from_candidate(
        candidate,
        release=release,
        staging_revision=str(receipt.get("staging_sha") or receipt.get("staging_revision")),
        publication_seal=str(
            (receipt.get("seal") or {}).get("path")
            or "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
        ),
        dry_run=True,
        repo_root=repo_root,
    )
    if str(plan["manifest_digest"]) != str(
        receipt.get("manifest_digest") or receipt.get("final_manifest_digest")
    ):
        raise PublicParityError(
            "reconstructed public plan manifest digest drifted from the receipt"
        )
    transport = hub if hub is not None else FakeFederalRegisterPublicHub()
    uploaded = transport.upload_files(
        release_file_bytes(release),
        repo_id=str(plan["target_repo"]),
        branch=str(plan["public_branch"]),
        base_revision=str(plan["old_sha"]),
    )
    reconstructed_sha = require_public_pin(
        {"public_sha": uploaded["public_revision"]},
        name="reconstructed_public_sha",
    )
    receipt_sha = require_public_pin(receipt)
    if reconstructed_sha != receipt_sha:
        raise PublicPinError(
            "reconstructed public SHA "
            f"{reconstructed_sha} does not equal receipt public SHA {receipt_sha}"
        )
    redownloaded = transport.redownload()
    descriptors = _public_descriptor_map(redownloaded, plan["artifacts"])
    return {
        "descriptors": descriptors,
        "fixture_only": True,
        "files": redownloaded,
        "live_remote": False,
        "plan": plan,
        "public_sha": receipt_sha,
        "reconstructed_sha": reconstructed_sha,
        "upload_file_count": int(plan["upload_file_count"]),
        "upload_bytes": int(plan["upload_bytes"]),
    }


# ---------------------------------------------------------------------------
# Live public verification loop (read-only)
# ---------------------------------------------------------------------------


def run_public_verification_loop(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
    admission: Mapping[str, Any] | None = None,
    fulltext: Mapping[str, Any] | None = None,
    staging_canary: Mapping[str, Any] | None = None,
    hub: FakeFederalRegisterPublicHub | None = None,
) -> dict[str, Any]:
    """Run the deterministic fixture parity loop (never live evidence)."""

    bound_receipt = (
        dict(receipt)
        if receipt is not None
        else load_publication_receipt(repo_root=repo_root)
    )
    public_sha = require_public_pin(bound_receipt)
    report = (
        dict(candidate)
        if candidate is not None
        else load_candidate_report(repo_root=repo_root)
    )
    cutoff = (
        dict(inventory)
        if inventory is not None
        else load_cutoff_inventory(repo_root=repo_root)
    )
    admitted = (
        dict(admission)
        if admission is not None
        else load_admission_report(repo_root=repo_root)
    )
    coverage = (
        dict(fulltext)
        if fulltext is not None
        else load_fulltext_coverage(repo_root=repo_root)
    )
    staged = (
        dict(staging_canary)
        if staging_canary is not None
        else load_staging_canary_report(repo_root=repo_root)
    )
    if str(staged.get("staging_revision") or "") != str(bound_receipt.get("staging_sha") or ""):
        raise PublicParityError(
            "publication receipt staging SHA does not match the sealed staging canary"
        )
    if str(staged.get("manifest_digest") or "") != str(
        bound_receipt.get("manifest_digest") or ""
    ):
        raise PublicParityError(
            "publication receipt manifest digest does not match the staging canary"
        )

    reconstructed = reconstruct_public_revision(
        repo_root=repo_root,
        receipt=bound_receipt,
        candidate=report,
        hub=hub,
    )
    public_descriptors = reconstructed["descriptors"]
    manifest_cmp = compare_public_to_candidate(public_descriptors, report)
    receipt_cmp = compare_public_to_receipt(reconstructed["files"], bound_receipt)
    admission_cmp = compare_cutoff_admission(
        report, cutoff, admitted, fulltext=coverage or None
    )
    try:
        parity = check_fulltext_key_family_parity(
            report, public_descriptors, fulltext=coverage or None
        )
    except CanaryParityError as exc:
        raise PublicParityError(str(exc)) from exc
    viewer = verify_viewer_configs(
        report.get("configs") and {"default_config": DEFAULT_CONFIG_NAME}
    )
    if str(viewer.get("default_config") or "") != DEFAULT_CONFIG_NAME:
        raise CheckFederalRegisterPublicError(
            "default Viewer config is not the v2 release profile"
        )
    try:
        traces = run_bounded_canary_traces(
            reconstructed["files"],
            public_descriptors,
            staging_revision=public_sha,
            budgets=PUBLIC_BUDGETS,
        )
    except CanaryBudgetError as exc:
        raise PublicBudgetError(str(exc)) from exc
    traces["revision"] = public_sha
    if traces.get("within_budget") is not True:
        raise PublicBudgetError("sparse public queries exceeded declared budgets")
    if int(traces["bytes"]) > int(traces["budgets"]["max_bytes"]):
        raise PublicBudgetError("public redownload exceeded max_bytes")
    if int(traces["shard_count"]) > int(traces["budgets"]["max_shards"]):
        raise PublicBudgetError("public redownload exceeded max_shards")
    for query in traces.get("queries") or []:
        if query.get("bounded") is not True or query.get("justified_only") is not True:
            raise PublicBudgetError(f"query {query.get('id')!r} is not justified/bounded")
        if int(query.get("bytes") or 0) > int(traces["budgets"]["max_query_bytes"]):
            raise PublicBudgetError(f"query {query.get('id')!r} exceeded max_query_bytes")

    return {
        "admission": admission_cmp,
        "candidate": report,
        "inventory": admission_cmp["inventory"],
        "fixture_only": True,
        "live_remote": False,
        "manifest": manifest_cmp,
        "parity": parity,
        "plan": reconstructed["plan"],
        "public_sha": public_sha,
        "receipt": bound_receipt,
        "receipt_parity": receipt_cmp,
        "redownloaded": reconstructed["files"],
        "reconstructed_sha": reconstructed["reconstructed_sha"],
        "staging_canary": {
            "manifest_digest": staged.get("manifest_digest"),
            "path": DEFAULT_STAGING_CANARY_RELPATH.as_posix(),
            "staging_revision": staged.get("staging_revision"),
            "task_id": staged.get("task_id") or STAGING_CANARY_TASK_ID,
        },
        "traces": traces,
        "viewer": viewer,
    }


def build_federal_public_canary_report(
    *,
    repo_root: Path | str | None = None,
    loop: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sealed public-revision canary receipt."""

    executed = (
        dict(loop)
        if loop is not None
        else run_public_verification_loop(repo_root=repo_root)
    )
    live_remote = executed.get("live_remote") is True
    plan = executed["plan"]
    candidate = executed["candidate"]
    receipt = executed["receipt"]
    public_sha = require_public_pin({"public_sha": executed["public_sha"]})
    report: dict[str, Any] = {
        "acceptance": {
            "bounded_canary_traces": True,
            "credentials_environment_only": True,
            "cutoff_admission_parity": True,
            "default_viewer_coherent": True,
            "fixture_only_rejected": live_remote,
            "full_text_disposition_reconciled": True,
            "immutable_public_revision": True,
            "key_parity": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_remote_mutation": True,
            "no_unexpected_operations": True,
            "publication_receipt_bound": True,
            "public_artifacts_equal_staged_candidate": True,
            "public_pin_immutable": True,
            "read_only": True,
            "secrets_absent": True,
            "semantic_family_reconciled": True,
            "sparse_queries_within_budget": True,
            "viewer_schema_coherent": True,
            "zero_unexpected_operations": True,
        },
        "base_revision": plan["base_revision"],
        "budgets": dict(executed["traces"]["budgets"]),
        "canary": {
            "bytes": executed["traces"]["bytes"],
            "queries": executed["traces"]["queries"],
            "query_modes": list(QUERY_MODES),
            "shard_count": executed["traces"]["shard_count"],
            "traces": executed["traces"]["traces"],
            "within_budget": True,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "default_config": DEFAULT_CONFIG_NAME,
        "depends_on": list(DEPENDS_ON),
        "fixture_only": not live_remote,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "inventory": dict(executed["inventory"]),
        "legacy_files_deleted": False,
        "live_network": live_remote,
        "live_public": live_remote,
        "manifest_digest": plan["manifest_digest"],
        "manifest_parity": dict(executed["manifest"]),
        "mutation_executed": False,
        "network_required": live_remote,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "old_sha": require_immutable_revision(receipt.get("old_sha"), name="old_sha"),
        "operations": ["download"],
        "parity": {
            "admission": dict(executed["admission"]),
            "family": True,
            "full_text": True,
            "key": True,
            **{
                key: value
                for key, value in dict(executed["parity"]).items()
                if key != "key_pairs"
            },
            "key_count": len(executed["parity"].get("key_pairs") or []),
        },
        "phase": "federal_public",
        "plan_digest": plan["plan_digest"],
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": public_sha,
        "public_sha": public_sha,
        "publication_receipt": {
            "manifest_digest": receipt.get("manifest_digest"),
            "old_sha": receipt.get("old_sha"),
            "path": DEFAULT_RECEIPT_RELPATH.as_posix(),
            "public_sha": public_sha,
            "staging_sha": receipt.get("staging_sha"),
            "task_id": PUBLICATION_TASK_ID,
        },
        "read_only": True,
        "receipt_parity": dict(executed["receipt_parity"]),
        "release_point": plan.get("release_point")
        or candidate.get("release_point")
        or "federal-register/v2/2026-08-10",
        "release_profile": plan.get("release_profile")
        or candidate.get("release_profile")
        or RELEASE_PROFILE,
        "release_root_cid": plan["release_root_cid"],
        "remote_write_contacted": False,
        "required_semantic_families": list(
            candidate.get("required_semantic_families") or required_semantic_families()
        ),
        "rollback": {
            "additive_only": True,
            "previous_public_pin": PRODUCTION_REVISION,
            "rollback_target": PRODUCTION_REVISION,
        },
        "schema": CANARY_SCHEMA,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_canary": dict(executed["staging_canary"]),
        "staging_revision": require_immutable_revision(
            receipt.get("staging_sha"), name="staging_sha"
        ),
        "staging_sha": require_immutable_revision(
            receipt.get("staging_sha"), name="staging_sha"
        ),
        "status": "passed",
        "target": DEFAULT_DATASET_REPO,
        "target_repo": DEFAULT_DATASET_REPO,
        "task_id": TASK_ID,
        "tokens_used": False,
        "transport": (
            "immutable_hub_read_only" if live_remote else "in_memory_fixture_public"
        ),
        "unexpected_operations": [],
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "viewer": dict(executed["viewer"]),
        "visibility_changed": False,
    }
    return seal_report(report)


def _compare_canary_reports(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    keys = (
        "schema",
        "task_id",
        "goal_id",
        "dataset_repo_id",
        "target_repo",
        "public_branch",
        "public_sha",
        "public_revision",
        "old_sha",
        "staging_sha",
        "base_revision",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "observation_cutoff",
        "fixture_only",
        "live_network",
        "live_public",
        "network_required",
        "phase",
        "producer",
        "program_id",
        "code_version",
        "status",
        "read_only",
        "previous_public_pin",
        "mutation_executed",
        "remote_write_contacted",
    )
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(key)
    fresh_acc = fresh.get("acceptance") if isinstance(fresh.get("acceptance"), Mapping) else {}
    sealed_acc = sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    for key, expected in fresh_acc.items():
        if sealed_acc.get(key) != expected:
            mismatches.append(f"acceptance.{key}")
    if list(fresh.get("operations") or []) != list(sealed.get("operations") or []):
        mismatches.append("operations")
    if sealed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    if sealed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    return mismatches


def assert_public_pin_contract(report: Mapping[str, Any]) -> None:
    """Refuse fixture-only substitutes for the recorded public pin."""

    if report.get("fixture_only") is not False:
        raise PublicPinError(
            "refusing fixture-only canary; --require-public-pin demands "
            "the recorded immutable public SHA"
        )
    if report.get("live_public") is not True:
        raise PublicPinError("public canary must identify a live public redownload")
    if report.get("live_network") is not True:
        raise PublicPinError("public canary must prove live read-only Hub contact")
    if report.get("network_required") is not True:
        raise PublicPinError("live public evidence must remain network-required")
    if str(report.get("transport") or "") != "immutable_hub_read_only":
        raise PublicPinError("public canary transport must be immutable_hub_read_only")
    if report.get("status") not in {"passed", "ok", True}:
        raise PublicPinError(
            f"public canary status is {report.get('status')!r}"
        )
    pin = require_public_pin(report)
    if str(report.get("public_revision") or "") != pin:
        raise PublicPinError("public_revision must equal public_sha")
    if str(report.get("phase") or "") != "federal_public":
        raise PublicPinError(
            f"canary phase must be federal_public, got {report.get('phase')!r}"
        )
    if report.get("read_only") is not True:
        raise PublicPinError("public canary must be read-only")
    if report.get("mutation_executed") is True:
        raise PublicPinError("public canary must not execute a Hub mutation")
    if report.get("remote_write_contacted") is True:
        raise PublicPinError("public canary must not contact a remote write path")
    if report.get("visibility_changed") is True:
        raise PublicPinError("public canary must not change visibility")
    if report.get("unexpected_operations"):
        raise PublicPinError("public canary recorded unexpected operations")
    if list(report.get("operations") or []) != ["download"]:
        raise PublicPinError("public canary may record only read-only downloads")
    if str(report.get("previous_public_pin") or "") != PRODUCTION_REVISION:
        raise PublicPinError("previous public pin drifted from the sealed rollback pin")
    if pin == PRODUCTION_REVISION:
        raise PublicPinError("public pin must be the new revision, not the previous pin")
    if pin == str(report.get("old_sha") or ""):
        raise PublicPinError("public pin must differ from old SHA")
    if pin == str(report.get("staging_sha") or ""):
        raise PublicPinError("public pin must differ from staging SHA")
    receipt = report.get("publication_receipt")
    if not isinstance(receipt, Mapping):
        raise PublicPinError("public canary is missing the LCR-065 receipt binding")
    receipt_pin = require_public_pin(receipt, name="publication_receipt.public_sha")
    if receipt_pin != pin:
        raise PublicPinError("canary public pin drifted from the publication receipt")
    if str(receipt.get("task_id") or "") != PUBLICATION_TASK_ID:
        raise PublicPinError("publication receipt binding must name LCR-065")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    required_flags = (
        "public_artifacts_equal_staged_candidate",
        "default_viewer_coherent",
        "semantic_family_reconciled",
        "full_text_disposition_reconciled",
        "sparse_queries_within_budget",
        "cutoff_admission_parity",
        "public_pin_immutable",
        "publication_receipt_bound",
        "read_only",
        "secrets_absent",
        "zero_unexpected_operations",
    )
    failed = [name for name in required_flags if acceptance.get(name) is not True]
    if failed:
        raise PublicPinError(
            "public canary acceptance flags failed: " + ", ".join(failed)
        )
    viewer = report.get("viewer") if isinstance(report.get("viewer"), Mapping) else {}
    if viewer.get("ok") is not True or viewer.get("schema_coherent") is not True:
        raise PublicPinError("default Viewer is not coherent")
    if str(viewer.get("default_config") or report.get("default_config") or "") != DEFAULT_CONFIG_NAME:
        raise PublicPinError("default Viewer config is not the v2 release profile")


def check_federal_public_release(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_public_pin: bool = False,
) -> dict[str, Any]:
    """Validate fixture evidence or a sealed immutable live public canary."""

    pin_required = bool(require_public_pin)
    extract_pin = globals()["require_public_pin"]
    receipt = load_publication_receipt(repo_root=repo_root)
    receipt_check = check_publication_receipt(receipt, repo_root=repo_root)
    if receipt_check.get("ok") is not True:
        raise PublicPinError("LCR-065 publication receipt check failed")

    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(repo_root)
    )
    if not sealed_path.is_file():
        raise CheckFederalRegisterPublicError(
            f"sealed public canary report not found: {DEFAULT_REPORT_RELPATH.as_posix()}"
        )
    sealed = load_json_mapping(sealed_path)

    if sealed.get("schema") != CANARY_SCHEMA:
        raise CheckFederalRegisterPublicError(
            f"sealed canary schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise CheckFederalRegisterPublicError(
            f"sealed canary task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("visibility_change_allowed") is True:
        raise CheckFederalRegisterPublicError("canary must never allow visibility changes")

    require_immutable_revision(sealed.get("public_sha"), name="sealed.public_sha")
    try:
        validate_repo_id(
            str(sealed.get("target_repo") or sealed.get("dataset_repo_id")),
            name="target_repo",
        )
    except ResolverError as exc:
        raise PublicRemoteError(str(exc)) from exc

    if pin_required:
        assert_public_pin_contract(sealed)
        if extract_pin(sealed) != extract_pin(receipt):
            raise PublicPinError(
                "sealed public pin does not equal the LCR-065 receipt public SHA"
            )
        if str(sealed.get("manifest_digest") or "") != str(
            receipt.get("manifest_digest") or receipt.get("final_manifest_digest") or ""
        ):
            raise PublicPinError(
                "sealed public canary manifest differs from the publication receipt"
            )
        if str(sealed.get("staging_sha") or "") != str(
            receipt.get("staging_sha") or receipt.get("staging_revision") or ""
        ):
            raise PublicPinError(
                "sealed public canary staging SHA differs from the publication receipt"
            )
        expected_digest = seal_report(sealed).get("content_digest")
        if sealed.get("content_digest") != expected_digest:
            raise PublicPinError("sealed public canary digest is stale")
        reject_credentials_in_payload(sealed, label="sealed_federal_public_canary")
        viewer = verify_viewer_configs(sealed.get("viewer") or {})
        if not viewer.get("ok"):
            raise CheckFederalRegisterPublicError("sealed canary viewer policy failed")
        return {
            "check": "pass",
            "default_viewer_coherent": True,
            "fixture_only": False,
            "full_text_disposition_reconciled": True,
            "manifest_digest": sealed["manifest_digest"],
            "mismatches": [],
            "network_required": True,
            "observation_cutoff": sealed.get("observation_cutoff"),
            "ok": True,
            "old_sha": sealed.get("old_sha"),
            "path": DEFAULT_REPORT_RELPATH.as_posix(),
            "phase": "federal_public",
            "public_artifacts_equal_staged_candidate": True,
            "public_sha": extract_pin(sealed),
            "read_only": True,
            "require_public_pin": True,
            "schema": CANARY_SCHEMA,
            "semantic_family_reconciled": True,
            "sparse_queries_within_budget": True,
            "staging_sha": sealed.get("staging_sha"),
            "task_id": TASK_ID,
            "target_repo": sealed.get("target_repo"),
            "viewer_ok": True,
        }

    fresh = build_federal_public_canary_report(repo_root=repo_root)
    mismatches = _compare_canary_reports(fresh, sealed)
    if mismatches:
        raise CheckFederalRegisterPublicError(
            "federal public canary check failed: " + ", ".join(mismatches[:16])
        )

    reject_credentials_in_payload(sealed, label="sealed_federal_public_canary")
    viewer = verify_viewer_configs(sealed.get("viewer") or {})
    if not viewer.get("ok"):
        raise CheckFederalRegisterPublicError("sealed canary viewer policy failed")

    return {
        "check": "pass",
        "default_viewer_coherent": True,
        "fixture_only": True,
        "full_text_disposition_reconciled": True,
        "manifest_digest": fresh["manifest_digest"],
        "mismatches": [],
        "network_required": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "old_sha": fresh["old_sha"],
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "phase": "federal_public",
        "public_artifacts_equal_staged_candidate": True,
        "public_sha": fresh["public_sha"],
        "read_only": True,
        "require_public_pin": pin_required,
        "schema": CANARY_SCHEMA,
        "semantic_family_reconciled": True,
        "sparse_queries_within_budget": True,
        "staging_sha": fresh["staging_sha"],
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
        "viewer_ok": True,
    }


def run_remote_canary(
    *,
    repo_id: str,
    revision: str,
    publication_receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    artifact_descriptors: Sequence[Mapping[str, Any]] | None = None,
    remote_descriptors: Sequence[Mapping[str, Any]] | None = None,
    fetch_file: Callable[[str, str, str], bytes] | None = None,
    inventory: Mapping[str, Any] | None = None,
    admission: Mapping[str, Any] | None = None,
    fulltext: Mapping[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Canary explicit immutable public coordinates via injected read APIs.

    The complete remote descriptor listing is compared to the complete
    candidate inventory. Only bounded control/family samples are downloaded,
    and every downloaded byte is rehashed. There is no local-byte fallback.
    """

    try:
        dataset = validate_repo_id(repo_id, name="repo_id")
        pin = validate_immutable_revision(revision, name="revision")
    except (ResolverError, MutableRevisionError) as exc:
        raise PublicRemoteError(str(exc)) from exc
    if dataset != DEFAULT_DATASET_REPO:
        raise PublicRemoteError(
            f"remote canary target must be {DEFAULT_DATASET_REPO!r}"
        )
    if not isinstance(publication_receipt, Mapping):
        raise PublicRemoteError("live canary requires the sealed publication receipt")
    receipt = dict(publication_receipt)
    if receipt.get("fixture_only") is not False:
        raise PublicRemoteError("live canary refuses a fixture publication receipt")
    if receipt.get("live_network") is not True:
        raise PublicRemoteError("publication receipt does not prove a live network write")
    if receipt.get("mutation_executed") is not True:
        raise PublicRemoteError("publication receipt does not prove the public commit")
    if receipt.get("remote_write_contacted") is not True:
        raise PublicRemoteError("publication receipt does not bind the remote write")
    if require_public_pin(receipt) != pin:
        raise PublicRemoteError("publication receipt revision differs from requested pin")
    if str(receipt.get("target_repo") or receipt.get("dataset_repo_id") or "") != dataset:
        raise PublicRemoteError("publication receipt target differs from requested repo")
    if not callable(fetch_file):
        raise PublicRemoteError(
            "remote Hub canary requires an injected read-only byte fetcher"
        )
    if not artifact_descriptors or not remote_descriptors:
        raise PublicRemoteError(
            "remote Hub canary requires complete candidate and remote descriptors"
        )

    expected = _descriptor_index(list(artifact_descriptors), label="candidate")
    observed = _descriptor_index(list(remote_descriptors), label="remote")
    if set(expected) != set(observed):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        details = [*(f"missing:{path}" for path in missing[:8])]
        details.extend(f"extra:{path}" for path in extra[:8])
        raise PublicParityError(
            "remote descriptor path set differs from candidate: "
            + "; ".join(details)
        )
    for path, descriptor in expected.items():
        remote = observed[path]
        for field in ("sha256", "size_bytes"):
            if remote.get(field) != descriptor.get(field):
                raise PublicParityError(
                    f"remote descriptor {path} {field} differs from candidate"
                )
        for field in ("content_cid", "family", "first_key", "last_key", "row_count"):
            expected_value = descriptor.get(field)
            remote_value = remote.get(field)
            if expected_value not in (None, "") and remote_value not in (
                None,
                "",
                expected_value,
            ):
                raise PublicParityError(
                    f"remote descriptor {path} {field} differs from candidate"
                )
            if remote_value in (None, ""):
                remote[field] = expected_value

    selected = [path for path in CONTROL_INDEXES if path in expected]
    represented = {
        str(expected[path].get("family") or "") for path in selected
    }
    for path, descriptor in sorted(expected.items()):
        family = str(descriptor.get("family") or "")
        if family and family not in represented:
            selected.append(path)
            represented.add(family)
    if len(selected) > int(PUBLIC_BUDGETS["max_shards"]):
        raise PublicBudgetError("remote canary selection exceeds max_shards")

    fetched: dict[str, bytes] = {}
    total_bytes = 0
    for path in selected:
        remote_path = str(expected[path].get("remote_path") or path)
        if remote_path.startswith("/") or ".." in Path(remote_path).parts:
            raise PublicParityError(
                f"unsafe remote artifact path: {remote_path!r}"
            )
        try:
            blob = fetch_file(dataset, pin, remote_path)
        except Exception as exc:
            raise PublicRemoteError(f"remote fetch failed for {path}: {exc}") from exc
        if not isinstance(blob, bytes):
            raise PublicRemoteError(f"remote fetcher returned non-bytes for {path}")
        descriptor = expected[path]
        if hashlib.sha256(blob).hexdigest() != descriptor["sha256"]:
            raise PublicParityError(f"redownloaded bytes drifted for {path}")
        if len(blob) != descriptor["size_bytes"]:
            raise PublicParityError(f"redownloaded size drifted for {path}")
        total_bytes += len(blob)
        if total_bytes > int(PUBLIC_BUDGETS["max_bytes"]):
            raise PublicBudgetError("remote canary exceeded max_bytes")
        fetched[path] = blob

    report = (
        dict(candidate)
        if isinstance(candidate, Mapping)
        else load_candidate_report(repo_root=repo_root)
    )
    nested = report.get("candidate")
    if isinstance(nested, Mapping):
        for key in (
            "manifest_digest",
            "observation_cutoff",
            "release_point",
            "release_profile",
            "release_root_cid",
        ):
            report.setdefault(key, nested.get(key))
    report["descriptors"] = [dict(item) for item in artifact_descriptors]
    receipt_manifest = str(
        receipt.get("manifest_digest") or receipt.get("final_manifest_digest") or ""
    )
    if report.get("manifest_digest") != receipt_manifest:
        raise PublicParityError("publication receipt does not bind candidate manifest")

    cutoff = (
        dict(inventory)
        if isinstance(inventory, Mapping)
        else load_cutoff_inventory(repo_root=repo_root)
    )
    admitted = (
        dict(admission)
        if isinstance(admission, Mapping)
        else load_admission_report(repo_root=repo_root)
    )
    coverage = (
        dict(fulltext)
        if isinstance(fulltext, Mapping)
        else load_fulltext_coverage(repo_root=repo_root)
    )
    manifest_cmp = compare_public_to_candidate(observed, report)
    admission_cmp = compare_cutoff_admission(
        report,
        cutoff,
        admitted,
        fulltext=coverage or None,
    )
    try:
        parity = check_fulltext_key_family_parity(
            report,
            observed,
            fulltext=coverage or None,
        )
        traces = run_bounded_canary_traces(
            fetched,
            observed,
            staging_revision=pin,
            budgets=PUBLIC_BUDGETS,
        )
    except CanaryBudgetError as exc:
        raise PublicBudgetError(str(exc)) from exc
    except CanaryParityError as exc:
        raise PublicParityError(str(exc)) from exc

    old_sha = require_immutable_revision(receipt.get("old_sha"), name="old_sha")
    staging_sha = require_immutable_revision(
        receipt.get("staging_sha") or receipt.get("staging_revision"),
        name="staging_sha",
    )
    loop = {
        "admission": admission_cmp,
        "candidate": report,
        "fixture_only": False,
        "inventory": admission_cmp["inventory"],
        "live_remote": True,
        "manifest": manifest_cmp,
        "parity": parity,
        "plan": {
            "base_revision": old_sha,
            "manifest_digest": receipt_manifest,
            "plan_digest": receipt.get("plan_digest"),
            "release_point": report.get("release_point"),
            "release_profile": report.get("release_profile") or RELEASE_PROFILE,
            "release_root_cid": report.get("release_root_cid"),
            "upload_bytes": sum(item["size_bytes"] for item in expected.values()),
            "upload_file_count": len(expected),
        },
        "public_sha": pin,
        "receipt": receipt,
        "receipt_parity": {
            "compared": len(expected),
            "exact_match": True,
            "mismatches": [],
            "ok": True,
            "public_sha": pin,
            "receipt_file_count": len(expected),
        },
        "redownloaded": fetched,
        "reconstructed_sha": pin,
        "staging_canary": {
            "manifest_digest": receipt_manifest,
            "path": DEFAULT_STAGING_CANARY_RELPATH.as_posix(),
            "staging_revision": staging_sha,
            "task_id": STAGING_CANARY_TASK_ID,
        },
        "traces": traces,
        "viewer": verify_viewer_configs(),
    }
    return build_federal_public_canary_report(repo_root=repo_root, loop=loop)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_federal_register_public_release.py",
        description=(
            "Redownload and canary the immutable Federal Register public "
            "revision recorded by the LCR-065 publication receipt."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the sealed federal_public_canary.json against a rebuilt public loop.",
    )
    parser.add_argument(
        "--require-public-pin",
        action="store_true",
        help="Refuse fixture-only canaries; require the recorded immutable public SHA.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Rebuild and write docs/reports/legal_corpora_reindex/federal_public_canary.json.",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="Optional explicit Hub repo for opt-in remote canary.",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional explicit immutable 40-hex public revision.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Opt in to remote Hub contact (requires --repo-id and --revision).",
    )
    parser.add_argument(
        "--canary-report",
        type=Path,
        default=None,
        help="Override path to the sealed federal public canary report.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Override path to the LCR-065 publication receipt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the check/receipt JSON (default: stdout).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except (
        PublishFederalRegisterError,
        PublishSafetyError,
        CheckFederalRegisterPublicError,
        StageFederalRegisterError,
        StageSafetyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.require_public_pin and not (args.check or args.write_report or args.network):
            # Official validation pairs this flag with --check. A bare
            # --require-public-pin still rebuilds and checks the sealed report.
            args.check = True

        if args.write_report:
            report = build_federal_public_canary_report()
            if args.require_public_pin:
                assert_public_pin_contract(report)
            target = args.canary_report or default_report_path()
            write_canary_report(report, path=target)
            write_json(
                args.output,
                {
                    "ok": True,
                    "path": DEFAULT_REPORT_RELPATH.as_posix(),
                    "public_sha": report["public_sha"],
                    "status": "report_written",
                    "task_id": TASK_ID,
                },
            )
            return 0

        if args.check:
            result = check_federal_public_release(
                path=args.canary_report,
                require_public_pin=bool(args.require_public_pin),
            )
            write_json(args.output, result)
            return 0 if result.get("ok") else 1

        remote_repo = args.repo_id or os.environ.get(REMOTE_REPO_ENV) or None
        remote_rev = args.revision or os.environ.get(REMOTE_REVISION_ENV) or None
        remote_env_enabled = str(os.environ.get(REMOTE_ENABLE_ENV) or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if args.network or remote_env_enabled:
            if not remote_repo or not remote_rev:
                raise PublicRemoteError(
                    "remote canary requires explicit public coordinates "
                    f"(--repo-id/--revision or ${REMOTE_REPO_ENV}/"
                    f"${REMOTE_REVISION_ENV}); refusing to infer a mutable revision"
                )
            receipt = run_remote_canary(repo_id=remote_repo, revision=remote_rev)
            write_json(args.output, receipt)
            return 0

        report = build_federal_public_canary_report()
        if args.require_public_pin:
            assert_public_pin_contract(report)
        write_json(args.output, report)
        return 0 if report.get("status") == "passed" else 1

    except (
        CheckFederalRegisterPublicError,
        PublicBudgetError,
        PublicParityError,
        PublicPinError,
        PublicRemoteError,
        CanaryBudgetError,
        CanaryParityError,
        PublishFederalRegisterError,
        PublishSafetyError,
        StageFederalRegisterError,
        StageSafetyError,
        PublicationGateError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
