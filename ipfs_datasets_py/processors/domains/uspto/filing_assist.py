"""Safe Patent Center filing *assist* helpers (never sign / pay / submit).

This module prepares checklists, payment-label prep (no instruments), and
post-submit receipt inbox layout. Browser control lives in the attended ops
script and is hard-gated against signature, payment, and final-submission
clicks.

Allowed
-------
* Content-free filing checklist bound to a package digest
* Fee *category labels* / due indicators from already-exported metadata
* Receipt inbox folder prep + seal/import after a human files
* Capability checks that refuse sign/pay/submit automation

Forbidden
---------
* apply_signature / pay_fee / perform_final_submission
* Storing card numbers, deposit-account secrets, or signature images
* Fabricating acknowledgements or claiming filing without human artifacts
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    import_export_folder,
    utc_now_iso,
    write_export_package_sidecar,
)

FILING_ASSIST_SCHEMA: Final = "patlaw-filing-assist-v1"
CHECKLIST_SCHEMA: Final = "patlaw-filing-checklist-v1"
RECEIPT_WATCH_SCHEMA: Final = "patlaw-post-submit-receipts-v1"

ALLOWED_FILING_ASSIST_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "generate_filing_checklist",
        "payment_prep_labels_only",
        "attended_filing_assist_with_hard_barrier",
        "watch_post_submit_receipts",
        "import_post_submit_receipts",
        "navigate_patent_center_view_only",
    }
)

FORBIDDEN_FILING_ASSIST_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "apply_signature",
        "pay_fee",
        "charge_card",
        "perform_final_submission",
        "submit_to_uspto",
        "automate_patent_center_filing",
        "store_payment_instrument",
        "store_signature_image",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "mark_submitted_without_human",
    }
)

# Labels that automation must never click (case-insensitive substring match).
HARD_BARRIER_CLICK_LABELS: Final[tuple[str, ...]] = (
    "sign",
    "e-sign",
    "esign",
    "electronic signature",
    "certify",
    "certification",
    "rule 11.18",
    "11.18",
    "submit",
    "final submit",
    "file application",
    "pay",
    "payment",
    "pay fees",
    "pay fee",
    "checkout",
    "place order",
    "complete payment",
    "authorize payment",
    "charge",
    "deposit account",
    "credit card",
    "debit card",
    "billing",
)

# Safe navigation affordances (view / prep only).
SAFE_NAVIGATION_LABELS: Final[tuple[str, ...]] = (
    "home",
    "workbench",
    "new submission",
    "existing submissions",
    "applications",
    "search",
    "help",
    "documents",
    "download",  # post-submit receipt download is encouraged
)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z", re.I)
_APP_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9/_\-]{2,31}\Z")

# Heuristic receipt filename classifiers (content-free).
_ACK_HINTS = re.compile(
    r"(acknowledg|ack.?receipt|ear\b|electronic.?ack|filing.?receipt|submission.?receipt)",
    re.I,
)
_PAY_HINTS = re.compile(
    r"(payment|fee.?receipt|pay.?receipt|transaction.?receipt|invoice)",
    re.I,
)


class FilingAssistError(PortfolioAutomationError):
    """Fail-closed filing assist error."""


class ForbiddenFilingAssistError(FilingAssistError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            f"forbidden filing-assist capability: {capability}",
            code="forbidden_filing_assist",
        )
        self.capability = capability


def assert_filing_assist_capability(capability: str) -> None:
    key = str(capability or "").strip()
    if key in FORBIDDEN_FILING_ASSIST_CAPABILITIES:
        raise ForbiddenFilingAssistError(key)
    if key not in ALLOWED_FILING_ASSIST_CAPABILITIES:
        raise FilingAssistError(
            f"unknown filing-assist capability: {key}",
            code="unknown_filing_assist_capability",
        )


def is_hard_barrier_label(label: str) -> bool:
    """True if *label* matches a sign/pay/submit hard barrier."""
    text = " ".join(str(label or "").lower().split())
    if not text:
        return False
    # Allow post-submit download of payment/ack receipts.
    if "download" in text and "receipt" in text:
        return False
    for barrier in HARD_BARRIER_CLICK_LABELS:
        # Word-boundary match so "design" does not trip "sign".
        if re.search(rf"(?<![a-z0-9]){re.escape(barrier)}(?![a-z0-9])", text):
            return True
    return False


def assert_click_allowed(label: str) -> None:
    if is_hard_barrier_label(label):
        raise ForbiddenFilingAssistError("perform_final_submission")


@dataclass
class FilingChecklistStep:
    step_id: str
    ordinal: int
    actor: str  # "system" | "human" | "either"
    summary: str
    hard_barrier: bool = False
    automation_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "ordinal": self.ordinal,
            "actor": self.actor,
            "summary": self.summary,
            "hard_barrier": self.hard_barrier,
            "automation_allowed": self.automation_allowed,
        }


@dataclass
class FilingChecklist:
    schema: str = CHECKLIST_SCHEMA
    application_number: str = ""
    package_digest: str = ""
    package_path: str = ""
    patent_center_url: str = "https://patentcenter.uspto.gov"
    training: bool = False
    steps: list[FilingChecklistStep] = field(default_factory=list)
    payment_prep: dict[str, Any] = field(default_factory=dict)
    post_submit_receipt_dir: str = ""
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Human must Sign, Pay, and Submit in Patent Center. "
        "Automation stops at hard barriers and never stores payment instruments."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "application_number": self.application_number,
            "package_digest": self.package_digest,
            "package_path": self.package_path,
            "patent_center_url": self.patent_center_url,
            "training": self.training,
            "steps": [s.to_dict() for s in self.steps],
            "payment_prep": dict(self.payment_prep),
            "post_submit_receipt_dir": self.post_submit_receipt_dir,
            "warnings": list(self.warnings),
            "disclaimer": self.disclaimer,
            "hard_barrier_labels": list(HARD_BARRIER_CLICK_LABELS),
            "generated_at_utc": utc_now_iso(),
        }


def _normalize_app(app: str) -> str:
    text = str(app or "").strip().replace(",", "").replace(" ", "")
    if not text or not _APP_RE.match(text):
        raise FilingAssistError(
            "invalid application_number", code="invalid_application_number"
        )
    return text


def _normalize_digest(digest: str) -> str:
    text = str(digest or "").strip().lower()
    if text and not _SHA256_RE.match(text):
        raise FilingAssistError(
            "package_digest must be 64-char sha256 hex when provided",
            code="invalid_package_digest",
        )
    return text


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_package_digest(package_dir: Path) -> str:
    """Stable content digest of files under *package_dir* (sorted paths)."""
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise FilingAssistError("package_dir not found", code="missing_package_dir")
    h = hashlib.sha256()
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.name
        not in {
            "export_manifest.json",
            "authorization.json",
            "filing_checklist.json",
            "IMPORTED",
            "READY",
            ".DS_Store",
        }
    )
    if not files:
        raise FilingAssistError("package_dir has no files", code="empty_package")
    for path in files:
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_path(path).encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def load_payment_prep_labels(
    *,
    metadata_dir: Path | None = None,
    fees_json: Path | None = None,
) -> dict[str, Any]:
    """Extract non-secret fee *labels* from prior export metadata.

    Never returns card numbers, deposit-account numbers, or CVV.
    """
    assert_filing_assist_capability("payment_prep_labels_only")
    out: dict[str, Any] = {
        "fees_due_indicator": None,
        "fees_past_due_indicator": None,
        "fee_labels": [],
        "source": None,
        "note": (
            "Labels only. Pay yourself in Patent Center; "
            "automation never charges a payment instrument."
        ),
    }
    candidates: list[Path] = []
    if fees_json:
        candidates.append(Path(fees_json))
    if metadata_dir:
        md = Path(metadata_dir)
        candidates.extend(
            [
                md / "fees.json",
                md / "application_data.json",
                md / "application_data_v2.json",
                md / "public_application_data.json",
            ]
        )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, Mapping):
            continue
        if "feesDueIndicator" in data or "feesPastDueIndicator" in data:
            out["fees_due_indicator"] = data.get("feesDueIndicator")
            out["fees_past_due_indicator"] = data.get("feesPastDueIndicator")
            out["source"] = str(path)
            break
        # feePaymentHistory is a list of historical labels only
        hist = data.get("feePaymentHistory")
        if isinstance(hist, list) and hist:
            labels: list[str] = []
            for item in hist[:40]:
                if not isinstance(item, Mapping):
                    continue
                code = item.get("feeCode") or item.get("feeCodeDescriptionText")
                if code:
                    labels.append(str(code)[:120])
            if labels:
                out["fee_labels"] = labels
                out["source"] = str(path)
                # keep scanning for explicit due indicators if present later
    return out


def build_filing_checklist(
    *,
    application_number: str = "",
    package_dir: Path | None = None,
    package_digest: str = "",
    training: bool = False,
    metadata_dir: Path | None = None,
    state_root: Path | None = None,
    receipt_subdir: str = "post_submit_receipts",
) -> FilingChecklist:
    """Build a content-free checklist with hard barriers for human actions."""
    assert_filing_assist_capability("generate_filing_checklist")
    app = str(application_number or "").strip()
    if app:
        app = _normalize_app(app)

    digest = _normalize_digest(package_digest)
    package_path = ""
    warnings: list[str] = []
    if package_dir is not None:
        root = Path(package_dir).expanduser().resolve()
        package_path = str(root)
        if root.is_dir():
            try:
                computed = compute_package_digest(root)
                if digest and digest != computed:
                    warnings.append(
                        "provided package_digest does not match computed package digest"
                    )
                if not digest:
                    digest = computed
            except FilingAssistError as exc:
                warnings.append(f"package_digest:{exc.code}")
        else:
            warnings.append("package_dir missing")

    state = Path(state_root) if state_root else default_state_root()
    receipt_dir = state / receipt_subdir
    if app:
        receipt_dir = receipt_dir / app
    receipt_dir.mkdir(parents=True, exist_ok=True)

    url = (
        "https://patentcenter-training.uspto.gov"
        if training
        else "https://patentcenter.uspto.gov"
    )

    meta = Path(metadata_dir) if metadata_dir else None
    if meta is None and package_dir is not None:
        # Common layout from export-ui
        cand = Path(package_dir).parent / "metadata"
        if cand.is_dir():
            meta = cand
    payment = load_payment_prep_labels(metadata_dir=meta)

    digest_short = (digest[:16] + "…") if digest else "(unknown)"
    steps = [
        FilingChecklistStep(
            step_id="prep-package",
            ordinal=1,
            actor="system",
            summary=(
                f"Confirm local package at {package_path or '(path not set)'} "
                f"binds digest {digest_short}."
            ),
            automation_allowed=True,
        ),
        FilingChecklistStep(
            step_id="open-patent-center",
            ordinal=2,
            actor="either",
            summary=(
                f"Open Patent Center ({'training' if training else 'live'}) at {url}. "
                "Attended assist may navigate here with a saved login session."
            ),
            automation_allowed=True,
        ),
        FilingChecklistStep(
            step_id="navigate-workbench",
            ordinal=3,
            actor="either",
            summary=(
                "Navigate to New submission or Existing submissions / Workbench "
                "as appropriate. View-only navigation is allowed; no auto-file."
            ),
            automation_allowed=True,
        ),
        FilingChecklistStep(
            step_id="upload-or-review-docs",
            ordinal=4,
            actor="human",
            summary=(
                "Upload or attach package files yourself (or confirm existing "
                "matter documents). Automation does not complete filing uploads "
                "that lead to immediate submit."
            ),
            automation_allowed=False,
        ),
        FilingChecklistStep(
            step_id="human-sign-certify",
            ordinal=5,
            actor="human",
            summary=(
                "HARD BARRIER: Complete signatures and Rule 11.18 certification "
                "yourself. Automation never clicks Sign/Certify."
            ),
            hard_barrier=True,
            automation_allowed=False,
        ),
        FilingChecklistStep(
            step_id="human-pay",
            ordinal=6,
            actor="human",
            summary=(
                "HARD BARRIER: Pay fees yourself in Patent Center. "
                f"Prep labels only: due={payment.get('fees_due_indicator')!r}, "
                f"past_due={payment.get('fees_past_due_indicator')!r}. "
                "No card or deposit-account secrets are stored."
            ),
            hard_barrier=True,
            automation_allowed=False,
        ),
        FilingChecklistStep(
            step_id="human-submit",
            ordinal=7,
            actor="human",
            summary=(
                "HARD BARRIER: Press Submit yourself. Automation never performs "
                "final submission."
            ),
            hard_barrier=True,
            automation_allowed=False,
        ),
        FilingChecklistStep(
            step_id="download-receipts",
            ordinal=8,
            actor="either",
            summary=(
                "Download Electronic Acknowledgement Receipt, payment receipt, "
                f"and USPTO-converted artifacts into {receipt_dir}."
            ),
            automation_allowed=True,
        ),
        FilingChecklistStep(
            step_id="seal-and-import-receipts",
            ordinal=9,
            actor="system",
            summary=(
                "Seal receipt folder and import via portfolio_cli watch-receipts "
                "or inbox-import. Record human submission assertion on the handoff "
                f"with digest {digest_short} when using PatentCenterHandoff."
            ),
            automation_allowed=True,
        ),
    ]

    return FilingChecklist(
        application_number=app,
        package_digest=digest,
        package_path=package_path,
        patent_center_url=url,
        training=bool(training),
        steps=steps,
        payment_prep=payment,
        post_submit_receipt_dir=str(receipt_dir),
        warnings=warnings,
    )


def write_filing_checklist(checklist: FilingChecklist, dest: Path) -> Path:
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checklist.to_dict(), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def classify_receipt_filename(name: str) -> str:
    """Return acknowledgement | payment | other for a local filename."""
    base = Path(name).name
    if _ACK_HINTS.search(base):
        return "acknowledgement"
    if _PAY_HINTS.search(base):
        return "payment"
    return "other"


def prepare_receipt_inbox(
    *,
    application_number: str,
    state_root: Path | None = None,
    receipt_subdir: str = "post_submit_receipts",
) -> Path:
    """Ensure post-submit receipt drop folder exists; return path."""
    app = _normalize_app(application_number)
    state = Path(state_root) if state_root else default_state_root()
    folder = state / receipt_subdir / app
    folder.mkdir(parents=True, exist_ok=True)
    readme = folder / "README.txt"
    if not readme.is_file():
        readme.write_text(
            "Drop Electronic Acknowledgement Receipt (EAR), payment receipt,\n"
            "and USPTO-converted PDFs here after YOU submit in Patent Center.\n"
            "Then run: portfolio_cli.py watch-receipts --application-number "
            f"{app}\n"
            "This folder is never auto-submitted to USPTO.\n",
            encoding="utf-8",
        )
    return folder


def scan_receipt_folder(folder: Path) -> dict[str, Any]:
    root = Path(folder)
    if not root.is_dir():
        return {
            "path": str(root),
            "exists": False,
            "file_count": 0,
            "classifications": {},
        }
    files = [
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name
        not in {
            "README.txt",
            "export_manifest.json",
            "authorization.json",
            "IMPORTED",
            "READY",
            "filing_checklist.json",
            ".DS_Store",
        }
    ]
    classes: dict[str, list[str]] = {
        "acknowledgement": [],
        "payment": [],
        "other": [],
    }
    for p in files:
        classes[classify_receipt_filename(p.name)].append(p.name)
    mtimes = []
    for p in files:
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            pass
    newest = max(mtimes) if mtimes else None
    age = (time.time() - newest) if newest is not None else None
    return {
        "path": str(root),
        "exists": True,
        "file_count": len(files),
        "classifications": classes,
        "has_acknowledgement_hint": bool(classes["acknowledgement"]),
        "has_payment_hint": bool(classes["payment"]),
        "has_ready_marker": (root / "READY").is_file(),
        "already_imported": (root / "IMPORTED").is_file(),
        "newest_mtime_age_seconds": age,
        "stable": bool(age is not None and age >= 15.0 and files),
    }


def import_receipt_folder(
    folder: Path,
    *,
    application_number: str,
    tenant_id: str,
    authorizing_user: str,
    store_root: Path,
    classification: str = "confidential_application",
    require_acknowledgement_hint: bool = False,
) -> dict[str, Any]:
    """Seal + import a post-submit receipt folder (human-downloaded only)."""
    assert_filing_assist_capability("import_post_submit_receipts")
    status = scan_receipt_folder(folder)
    if status.get("already_imported"):
        return {"ok": False, "reason": "already_imported", **status}
    if int(status.get("file_count") or 0) <= 0:
        return {"ok": False, "reason": "empty", **status}
    if require_acknowledgement_hint and not status.get("has_acknowledgement_hint"):
        return {
            "ok": False,
            "reason": "missing_acknowledgement_filename_hint",
            "hint": "Rename EAR to include 'acknowledgement' or 'EAR', or pass --no-require-ack-hint",
            **status,
        }
    # Seal with public_official-friendly fallbacks handled by write_export_package_sidecar
    write_export_package_sidecar(
        Path(folder),
        application_number=application_number,
        tenant_id=tenant_id,
        authorizing_user=authorizing_user,
        classification=classification,
    )
    result = import_export_folder(
        Path(folder),
        tenant_id=tenant_id,
        application_number=application_number,
        authorizing_user=authorizing_user,
        store_root=store_root,
        classification=classification,
    )
    (Path(folder) / "IMPORTED").write_text(
        json.dumps(
            {
                "imported_at_utc": utc_now_iso(),
                "application_number": application_number,
                "tenant_id": tenant_id,
                "kind": "post_submit_receipts",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "result": result, **status}


def watch_and_import_receipts(
    *,
    application_number: str,
    state_root: Path | None = None,
    store_root: Path | None = None,
    tenant_id: str = "operator-default",
    authorizing_user: str = "operator:local",
    duration_seconds: float = 300.0,
    poll_seconds: float = 10.0,
    min_stable_seconds: float = 15.0,
    require_acknowledgement_hint: bool = False,
    classification: str = "confidential_application",
) -> dict[str, Any]:
    """Poll post-submit receipt folder and import when stable."""
    assert_filing_assist_capability("watch_post_submit_receipts")
    app = _normalize_app(application_number)
    state = Path(state_root) if state_root else default_state_root()
    folder = prepare_receipt_inbox(
        application_number=app, state_root=state
    )
    store = (
        Path(store_root).expanduser().resolve()
        if store_root
        else state / "private_store"
    )
    deadline = time.time() + max(5.0, float(duration_seconds))
    cycles = 0
    imported: dict[str, Any] | None = None
    last_status: dict[str, Any] = {}
    while time.time() < deadline:
        cycles += 1
        last_status = scan_receipt_folder(folder)
        age = last_status.get("newest_mtime_age_seconds")
        stable = bool(
            last_status.get("file_count")
            and age is not None
            and float(age) >= float(min_stable_seconds)
        ) or bool(last_status.get("has_ready_marker"))
        if last_status.get("already_imported"):
            return {
                "schema": RECEIPT_WATCH_SCHEMA,
                "ok": True,
                "reason": "already_imported",
                "cycles": cycles,
                "folder": str(folder),
                "status": last_status,
                "generated_at_utc": utc_now_iso(),
            }
        if stable and int(last_status.get("file_count") or 0) > 0:
            imported = import_receipt_folder(
                folder,
                application_number=app,
                tenant_id=tenant_id,
                authorizing_user=authorizing_user,
                store_root=store,
                classification=classification,
                require_acknowledgement_hint=require_acknowledgement_hint,
            )
            if imported.get("ok"):
                return {
                    "schema": RECEIPT_WATCH_SCHEMA,
                    "ok": True,
                    "cycles": cycles,
                    "folder": str(folder),
                    "imported": imported,
                    "generated_at_utc": utc_now_iso(),
                }
        time.sleep(max(1.0, float(poll_seconds)))
    return {
        "schema": RECEIPT_WATCH_SCHEMA,
        "ok": False,
        "reason": "timeout_no_stable_receipts",
        "cycles": cycles,
        "folder": str(folder),
        "status": last_status,
        "hint": (
            f"Drop EAR/payment PDFs into {folder} after human Submit, "
            "optionally add READY marker, then re-run watch-receipts."
        ),
        "generated_at_utc": utc_now_iso(),
    }


__all__ = [
    "ALLOWED_FILING_ASSIST_CAPABILITIES",
    "CHECKLIST_SCHEMA",
    "FILING_ASSIST_SCHEMA",
    "FORBIDDEN_FILING_ASSIST_CAPABILITIES",
    "FilingAssistError",
    "FilingChecklist",
    "FilingChecklistStep",
    "ForbiddenFilingAssistError",
    "HARD_BARRIER_CLICK_LABELS",
    "RECEIPT_WATCH_SCHEMA",
    "assert_click_allowed",
    "assert_filing_assist_capability",
    "build_filing_checklist",
    "classify_receipt_filename",
    "compute_package_digest",
    "import_receipt_folder",
    "is_hard_barrier_label",
    "load_payment_prep_labels",
    "prepare_receipt_inbox",
    "scan_receipt_folder",
    "sha256_path",
    "watch_and_import_receipts",
    "write_filing_checklist",
]
