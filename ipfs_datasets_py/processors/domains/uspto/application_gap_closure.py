"""Close remaining application diligence gaps with evidence packs.

Builds review-support packages for residual gaps that the rules/format audit
and prior-art loop leave open:

* **Foreign-patent corpus** — formal *named-gap acceptance* (gap stays visible;
  never claims foreign was searched) **or** optional EPO live-search path.
* **Family / PCT / ISR** — continuity + ISR/WO IDS evidence from exports.
* **Human diligence packs** — inventorship, new-matter, nonpublication, export
  control with IFW/ODP facts for operator review.

Hard rules
----------
* Not legal advice; not a completeness or patentability certification.
* Never Sign / Pay / Submit / auto-file IDS.
* Never silently mark foreign patents as searched.
* Human checklist confirmations require an explicit acknowledger name.
* Provisional title / inventorship deltas are **flags for human review**, not
  legal conclusions about priority support or inventorship correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    default_state_root,
    utc_now_iso,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
    FOREIGN_GAP_DISCLAIMER,
    build_and_persist_foreign_gap_package,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    load_export_temporal_anchors,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    inventory_package_dir,
    resolve_export_package_dir,
)

GAP_CLOSURE_SCHEMA: Final = "patlaw-application-gap-closure-v1"
FOREIGN_GAP_ACCEPTANCE_SCHEMA: Final = "patlaw-foreign-gap-acceptance-v1"
HUMAN_DILIGENCE_PACK_SCHEMA: Final = "patlaw-human-diligence-pack-v1"
FAMILY_PCT_PACK_SCHEMA: Final = "patlaw-family-pct-isr-pack-v1"

GAP_CLOSURE_DISCLAIMER: Final = (
    "Application gap-closure packages are decision support only — not legal "
    "advice, not a completeness certification, and not a patentability, "
    "priority-support, inventorship, export-control, or IDS determination. "
    "Named foreign gaps remain unsearched unless a later run records "
    "foreign_patents in searched_corpora. Sign/Pay/Submit remain human-only."
)

_HUMAN_ITEM_IDS: Final[tuple[str, ...]] = (
    "check:inventorship",
    "check:new-matter",
    "check:nonpublication",
    "check:export",
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _content_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_app(application_number: str) -> str:
    return re.sub(r"\D", "", str(application_number or ""))


def _latest_prior_art_run(state_root: Path, app: str) -> Path | None:
    base = state_root / "prior_art" / app
    if not base.is_dir():
        return None
    runs = sorted(
        [p for p in base.iterdir() if p.is_dir() and p.name.startswith("run-")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return runs[0] if runs else None


def _load_full_application_bag(app: str, state_root: Path) -> dict[str, Any]:
    """Return full Patent Center application_data bag when present."""
    candidates = [
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "application_data.json",
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "application_data_v2.json",
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "metadata"
        / "application_data.json",
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "public_application_data.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        data = _read_json(p)
        if data:
            return data
    return {}


def _ifw_codes(inventory: Mapping[str, Any]) -> set[str]:
    codes: set[str] = set()
    for f in inventory.get("files") or []:
        if not isinstance(f, Mapping):
            continue
        code = str(f.get("ifw_document_code") or "").strip().upper()
        if code:
            codes.add(code)
        name = str(f.get("name") or "")
        m = re.match(r"^(?:\d{7,8}_)?([A-Za-z0-9.]+)_", name)
        if m:
            codes.add(m.group(1).upper())
        # bare codes like OATH_....pdf
        m2 = re.match(r"^([A-Za-z0-9.]+)_", name)
        if m2:
            codes.add(m2.group(1).upper())
    # also scan ifw summary when available
    return codes


def _ifw_summary_docs(app: str, state_root: Path) -> list[dict[str, Any]]:
    for rel in (
        f"exports/{app}/patent_center_ui/metadata/ifw_document_summary.json",
        f"exports/{app}/patent_center_ui/package/ifw_document_summary.json",
    ):
        p = state_root / rel
        if p.is_file():
            data = _read_json(p)
            docs = data.get("documents") or []
            if isinstance(docs, list):
                return [d for d in docs if isinstance(d, Mapping)]
    return []


_HONORIFIC_RE = re.compile(
    r"^(?:mr|mrs|ms|miss|dr|prof|sir|mx)\.?\s+",
    re.I,
)


def _normalize_person_name(name: str) -> str:
    """Lowercase, strip honorifics/punctuation for inventorship set compare."""
    s = str(name or "").strip().lower()
    s = _HONORIFIC_RE.sub("", s)
    s = re.sub(r"[.,]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _inventor_names(bag: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for inv in bag.get("inventorBag") or bag.get("inventors") or []:
        if not isinstance(inv, Mapping):
            continue
        name = (
            inv.get("nameLineOneText")
            or inv.get("inventorNameText")
            or " ".join(
                str(x)
                for x in (
                    inv.get("firstName"),
                    inv.get("middleName"),
                    inv.get("lastName"),
                )
                if x
            ).strip()
        )
        name = str(name or "").strip()
        if name:
            # Drop honorific prefixes in display names from ODP
            name = _HONORIFIC_RE.sub("", name).strip()
            out.append(name)
    return out


def _title_from_bag(bag: Mapping[str, Any]) -> str:
    meta = bag.get("applicationMetaData") or bag
    if isinstance(meta, Mapping):
        return str(meta.get("inventionTitle") or meta.get("title") or "").strip()
    return ""


def _odp_api_key() -> str:
    return (
        os.environ.get("USPTO_ODP_API_KEY")
        or os.environ.get("ODP_API_KEY")
        or os.environ.get("USPTO_API_KEY")
        or ""
    ).strip()


def fetch_odp_application_snapshot(
    application_number: str,
    *,
    api_key: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Fetch a compact public ODP application snapshot (title, inventors, status).

    Returns ``{ok, application_number, title, inventors, status, filing_date,
    raw_meta_keys}`` — never raises on HTTP failure.
    """
    app = str(application_number or "").strip()
    key = (api_key if api_key is not None else _odp_api_key()).strip()
    empty = {
        "ok": False,
        "application_number": app,
        "title": "",
        "inventors": [],
        "status": "",
        "filing_date": "",
        "error": None,
    }
    if not app:
        empty["error"] = "application_number required"
        return empty
    if not key:
        empty["error"] = "USPTO_ODP_API_KEY not set"
        return empty

    # Prefer GET by application number; fall back to search.
    paths = [
        f"/api/v1/patent/applications/{re.sub(r'[^A-Za-z0-9]', '', app)}",
    ]
    digits = re.sub(r"\D", "", app)
    if digits and digits != app:
        paths.append(f"/api/v1/patent/applications/{digits}")

    last_err: str | None = None
    for path in paths:
        try:
            req = urllib.request.Request(
                f"https://api.uspto.gov{path}",
                headers={
                    "X-API-KEY": key,
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            bag = data.get("patentFileWrapperDataBag") or []
            if not bag and isinstance(data, Mapping):
                bag = [data]
            if not bag:
                last_err = "empty_bag"
                continue
            item = bag[0] if isinstance(bag[0], Mapping) else {}
            meta = item.get("applicationMetaData") or item
            if not isinstance(meta, Mapping):
                meta = {}
            inventors = []
            for inv in meta.get("inventorBag") or []:
                if isinstance(inv, Mapping):
                    n = inv.get("inventorNameText") or " ".join(
                        str(x)
                        for x in (inv.get("firstName"), inv.get("lastName"))
                        if x
                    )
                    if n:
                        inventors.append(str(n).strip())
            clean_inv = [
                _HONORIFIC_RE.sub("", n).strip() for n in inventors if n
            ]
            return {
                "ok": True,
                "application_number": str(
                    item.get("applicationNumberText") or app
                ),
                "title": str(meta.get("inventionTitle") or "").strip(),
                "inventors": clean_inv,
                "status": str(
                    meta.get("applicationStatusDescriptionText") or ""
                ).strip(),
                "filing_date": str(meta.get("filingDate") or "").strip(),
                "child_continuity": item.get("childContinuityBag") or [],
                "parent_continuity": item.get("parentContinuityBag") or [],
                "source": "odp_get",
                "error": None,
            }
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            continue

    # Search fallback
    try:
        q = digits or app
        body = json.dumps(
            {
                "q": f"applicationNumberText:{q}",
                "pagination": {"offset": 0, "limit": 1},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.uspto.gov/api/v1/patent/applications/search",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": key,
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        bag = data.get("patentFileWrapperDataBag") or []
        if bag and isinstance(bag[0], Mapping):
            item = bag[0]
            meta = item.get("applicationMetaData") or {}
            inventors = []
            for inv in (meta.get("inventorBag") or []):
                if isinstance(inv, Mapping):
                    n = inv.get("inventorNameText") or " ".join(
                        str(x)
                        for x in (inv.get("firstName"), inv.get("lastName"))
                        if x
                    )
                    if n:
                        inventors.append(str(n).strip())
            clean_inv = [
                _HONORIFIC_RE.sub("", n).strip() for n in inventors if n
            ]
            return {
                "ok": True,
                "application_number": str(
                    item.get("applicationNumberText") or app
                ),
                "title": str(meta.get("inventionTitle") or "").strip(),
                "inventors": clean_inv,
                "status": str(
                    meta.get("applicationStatusDescriptionText") or ""
                ).strip(),
                "filing_date": str(meta.get("filingDate") or "").strip(),
                "child_continuity": item.get("childContinuityBag") or [],
                "parent_continuity": item.get("parentContinuityBag") or [],
                "source": "odp_search",
                "error": None,
            }
        last_err = "search_empty"
    except Exception as exc:  # noqa: BLE001
        last_err = f"{type(exc).__name__}: {exc}"

    empty["error"] = last_err
    return empty


def _scan_extracted_text_for_isr(
    app: str, state_root: Path
) -> dict[str, Any]:
    """Find ISR / Written Opinion evidence in GraphRAG extracts."""
    hits: list[dict[str, str]] = []
    graphrag = state_root / "graphrag"
    if not graphrag.is_dir():
        return {"isr_mentioned": False, "wo_mentioned": False, "hits": []}

    builds = sorted(
        [p for p in graphrag.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    patterns = (
        (
            "isr_ids_cite",
            re.compile(
                r"International Search Report.*?PCT[/\s]?US\s*2025\s*/?\s*015067",
                re.I | re.S,
            ),
        ),
        (
            "wo_ids_cite",
            re.compile(
                r"Written Opinion.*?PCT[/\s]?US\s*2025\s*/?\s*015067",
                re.I | re.S,
            ),
        ),
        (
            "isr_form",
            re.compile(r"Form\s+PCT/?ISA/?210|International Search Report", re.I),
        ),
        (
            "wo_form",
            re.compile(
                r"Written Opinion of the International Searching Authority|"
                r"Form\s+PCT/?ISA/?237",
                re.I,
            ),
        ),
    )
    seen_paths: set[str] = set()
    for build in builds[:4]:
        ext = build / "extracted_text" / app
        if not ext.is_dir():
            continue
        for p in sorted(ext.glob("*.txt")):
            sp = str(p)
            if sp in seen_paths:
                continue
            seen_paths.add(sp)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for code, cre in patterns:
                if cre.search(text):
                    hits.append(
                        {
                            "code": code,
                            "path": sp,
                            "snippet": text[:120].replace("\n", " ").strip(),
                        }
                    )
        if hits:
            break

    codes = {h["code"] for h in hits}
    return {
        "isr_mentioned": any("isr" in c for c in codes),
        "wo_mentioned": any("wo" in c for c in codes),
        "hits": hits[:20],
    }


# ---------------------------------------------------------------------------
# Foreign gap formal acceptance
# ---------------------------------------------------------------------------


def accept_foreign_gap(
    *,
    application_number: str,
    run_dir: str | Path,
    acknowledger_name: str,
    statement: str | None = None,
    reason: str = "operator_accepts_named_gap_visible",
) -> dict[str, Any]:
    """Record formal acceptance that the foreign-patent gap remains unsearched.

    This does **not** mark foreign patents as searched. It only documents that
    a named human reviewed the foreign gap package and accepts proceeding with
    the gap remaining visible (IDS/remarks). EPO live search remains optional.
    """
    app = _normalize_app(application_number)
    run_path = Path(run_dir).expanduser().resolve()
    if not run_path.is_dir():
        return {
            "ok": False,
            "error": f"run directory not found: {run_path}",
            "code": "run_dir_missing",
        }
    ack = str(acknowledger_name or "").strip()
    if not ack:
        return {
            "ok": False,
            "error": "acknowledger_name required for foreign gap acceptance",
            "code": "acknowledger_required",
        }

    package_path = run_path / "foreign_gap_package.json"
    if not package_path.is_file():
        try:
            build_and_persist_foreign_gap_package(
                run_path, application_number=app
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"foreign gap package missing and rebuild failed: {exc}",
                "code": "foreign_package_missing",
            }

    package = _read_json(package_path)
    if package.get("foreign_searched") is True:
        return {
            "ok": True,
            "skipped": True,
            "reason": "foreign_already_searched",
            "message": (
                "Foreign corpus already marked searched; acceptance of an "
                "unsearched gap is not applicable."
            ),
            "run_dir": str(run_path),
        }

    stmt = statement or (
        "I reviewed the foreign-patent gap package. I accept that the "
        "foreign-patent corpus was not searched (reason recorded on the "
        "package) and that this named gap remains visible for IDS/remarks. "
        "This acceptance does not assert foreign coverage, novelty, or "
        "patentability. Optional EPO OPS live foreign search remains available."
    )
    acceptance = {
        "schema": FOREIGN_GAP_ACCEPTANCE_SCHEMA,
        "ok": True,
        "application_number": app,
        "run_id": run_path.name,
        "run_dir": str(run_path),
        "package_id": package.get("package_id"),
        "foreign_searched": False,
        "claims_foreign_coverage": False,
        "gap_remains_visible": True,
        "reason": reason,
        "package_reason": package.get("reason"),
        "named_gaps": package.get("named_gaps") or [],
        "acknowledger_name": ack,
        "acknowledged_at_utc": utc_now_iso(),
        "statement": stmt,
        "package_digest": _content_digest(package),
        "epo_optional_next_step": (
            "To actually search foreign patents: set EPO_OPS_KEY/EPO_OPS_SECRET "
            "and re-run check_prior_art.py --live-foreign, or supply "
            "--foreign-hits <file>."
        ),
        "disclaimer": FOREIGN_GAP_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }
    path = _write_json(run_path / "foreign_gap_acceptance.json", acceptance)

    # Also stamp a compact pointer under compliance_audits for the audit loader.
    return {
        "ok": True,
        "path": str(path),
        "acceptance": acceptance,
        "disclaimer": FOREIGN_GAP_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Family / PCT / ISR pack
# ---------------------------------------------------------------------------


def build_family_pct_isr_pack(
    application_number: str,
    *,
    state_root: Path | None = None,
    fetch_odp: bool = True,
) -> dict[str, Any]:
    """Build family continuity + PCT/ISR diligence evidence pack."""
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    bag = _load_full_application_bag(app, root)
    meta = bag.get("applicationMetaData") or {}
    if not isinstance(meta, Mapping):
        meta = {}
    anchors = load_export_temporal_anchors(app, state_root=root)

    parents = []
    for p in bag.get("parentContinuityBag") or []:
        if isinstance(p, Mapping):
            parents.append(dict(p))
    children = []
    for c in bag.get("childContinuityBag") or []:
        if isinstance(c, Mapping):
            children.append(dict(c))

    # Normalize child app numbers from bag (often messy)
    pct_children: list[dict[str, Any]] = []
    utility_children: list[dict[str, Any]] = []
    for c in children:
        child_no = str(
            c.get("childApplicationNumberText")
            or c.get("applicationNumberText")
            or ""
        ).strip()
        status = str(c.get("statusDescriptionText") or "").strip()
        entry = {
            "application_number": child_no,
            "filing_date": c.get("filingDate"),
            "status": status,
            "raw": {
                k: c.get(k)
                for k in (
                    "parentApplicationNumberText",
                    "childApplicationNumberText",
                    "applicationStatusCategory",
                    "aiaIndicator",
                )
                if k in c
            },
        }
        if re.search(r"PCT|US\d{2}/?\d+", child_no, re.I) or re.search(
            r"PCT|International Search", status, re.I
        ):
            pct_children.append(entry)
        else:
            utility_children.append(entry)

    # Provisional parent(s)
    provisionals: list[dict[str, Any]] = []
    for p in parents:
        pno = str(
            p.get("parentApplicationNumberText")
            or p.get("applicationNumberText")
            or ""
        ).strip()
        status = str(p.get("statusDescriptionText") or "").strip()
        entry = {
            "application_number": re.sub(r"\D", "", pno) or pno,
            "filing_date": p.get("filingDate"),
            "status": status,
            "raw": dict(p),
            "odp": None,
        }
        if fetch_odp and entry["application_number"]:
            entry["odp"] = fetch_odp_application_snapshot(
                entry["application_number"]
            )
        provisionals.append(entry)

    # PCT ODP snapshot when possible
    pct_odp: dict[str, Any] | None = None
    pct_export_status: dict[str, Any] = {"present": False}
    pct_app_candidates = []
    for c in pct_children:
        no = c["application_number"]
        pct_app_candidates.append(no)
        compact = re.sub(r"[^A-Za-z0-9]", "", no.upper())
        if compact:
            pct_app_candidates.append(compact)
            # PCTUS2025015067 form
            m = re.search(r"US(\d{2})(\d{5,})", compact)
            if m:
                pct_app_candidates.append(f"PCTUS{m.group(1)}{m.group(2)}")
    # also seed portfolio form
    pct_app_candidates.append("PCTUS2025015067")
    pct_app_candidates = list(dict.fromkeys(pct_app_candidates))

    if fetch_odp:
        for cand in pct_app_candidates:
            snap = fetch_odp_application_snapshot(cand)
            if snap.get("ok"):
                pct_odp = snap
                break

    for cand in ("PCTUS2025015067", "PCTUS2515067"):
        exp = root / "exports" / cand
        if exp.is_dir():
            idx = _read_json(
                exp / "patent_center_ui" / "package" / "export_index.json"
            )
            man = _read_json(
                exp / "patent_center_ui" / "package" / "export_manifest.json"
            )
            pct_export_status = {
                "present": True,
                "export_path": str(exp),
                "application_number": cand,
                "ifw_complete": False,
                "note": (
                    "Private Patent Center IFW export for PCT was incomplete "
                    "(auth/public lookup failures recorded on export_index). "
                    "Rely on continuity status + ISR/WO IDS cites + ODP status."
                ),
                "export_index_keys": list(idx.keys()) if idx else [],
                "manifest_entry_count": len(man.get("entries") or [])
                if man
                else 0,
            }
            break

    isr_text = _scan_extracted_text_for_isr(app, root)
    docs = _ifw_summary_docs(app, root)
    ids_docs = [
        d
        for d in docs
        if str(d.get("documentCode") or "").upper()
        in {"IDS", "1449", "892", "PTA.IDS", "REF.OTHER"}
    ]

    subject_title = str(
        meta.get("inventionTitle") or anchors.get("title") or ""
    ).strip()
    provisional_title_flags: list[dict[str, Any]] = []
    for prov in provisionals:
        odp = prov.get("odp") or {}
        ptitle = str(odp.get("title") or "").strip()
        if ptitle and subject_title and ptitle.upper() != subject_title.upper():
            provisional_title_flags.append(
                {
                    "code": "provisional_title_mismatch",
                    "severity": "human_review",
                    "provisional_application": prov.get("application_number"),
                    "provisional_title": ptitle,
                    "subject_title": subject_title,
                    "message": (
                        "Provisional invention title differs from the subject "
                        "application title. Human must confirm priority support "
                        "/ new-matter relative to the provisional disclosure "
                        "(title mismatch alone is not a legal conclusion)."
                    ),
                }
            )

    inventorship_flags: list[dict[str, Any]] = []
    subject_inv = _inventor_names(bag)
    for prov in provisionals:
        odp = prov.get("odp") or {}
        p_inv = list(odp.get("inventors") or [])
        if p_inv and subject_inv:
            # Normalize honorifics (e.g. "Mr. Tyrone Cunningham") so ODP
            # display noise does not invent a false inventorship delta.
            p_set = {_normalize_person_name(n) for n in p_inv if n}
            s_set = {_normalize_person_name(n) for n in subject_inv if n}
            p_set.discard("")
            s_set.discard("")
            added = sorted(s_set - p_set)
            removed = sorted(p_set - s_set)
            if added or removed:
                inventorship_flags.append(
                    {
                        "code": "inventorship_delta_vs_provisional",
                        "severity": "human_review",
                        "provisional_application": prov.get("application_number"),
                        "provisional_inventors": p_inv,
                        "subject_inventors": subject_inv,
                        "added_on_subject": added,
                        "removed_from_provisional": removed,
                        "message": (
                            "Inventor listing differs between provisional and "
                            "subject application. Confirm inventorship under "
                            "35 U.S.C. § 100/115 practice (human-only)."
                        ),
                    }
                )

    findings: list[dict[str, Any]] = []
    findings.extend(provisional_title_flags)
    findings.extend(inventorship_flags)

    if pct_children or pct_odp:
        findings.append(
            {
                "code": "pct_family_member_present",
                "severity": "info",
                "message": (
                    "PCT family member present with international search status "
                    "or continuity link."
                ),
                "pct_children": pct_children,
                "pct_odp_status": (pct_odp or {}).get("status"),
            }
        )
    if isr_text.get("isr_mentioned") or isr_text.get("wo_mentioned"):
        findings.append(
            {
                "code": "isr_wo_evidence_in_export",
                "severity": "pass",
                "message": (
                    "ISR and/or Written Opinion evidence found in GraphRAG "
                    "extracts (IDS NPL cites and/or REF.OTHER ISR forms)."
                ),
                "isr_mentioned": isr_text.get("isr_mentioned"),
                "wo_mentioned": isr_text.get("wo_mentioned"),
            }
        )
    else:
        findings.append(
            {
                "code": "isr_wo_evidence_not_found_in_extracts",
                "severity": "warning",
                "message": (
                    "No ISR/WO text hits in GraphRAG extracts for this app; "
                    "confirm ISR documents if PCT family exists."
                ),
            }
        )

    pack = {
        "schema": FAMILY_PCT_PACK_SCHEMA,
        "ok": True,
        "application_number": app,
        "subject_title": subject_title,
        "subject_inventors": subject_inv,
        "subject_status": str(
            meta.get("applicationStatusDescriptionText") or ""
        ),
        "patent_number": str(meta.get("patentNumber") or ""),
        "parents": parents,
        "children": children,
        "provisionals": provisionals,
        "pct_children": pct_children,
        "utility_children": utility_children,
        "pct_odp": pct_odp,
        "pct_export_status": pct_export_status,
        "isr_text_evidence": {
            "isr_mentioned": isr_text.get("isr_mentioned"),
            "wo_mentioned": isr_text.get("wo_mentioned"),
            "hit_count": len(isr_text.get("hits") or []),
            "hits": isr_text.get("hits") or [],
        },
        "ids_related_ifw_docs": [
            {
                "documentCode": d.get("documentCode"),
                "officialDate": d.get("officialDate") or d.get("mailRoomDate"),
                "documentDescription": d.get("documentDescription"),
            }
            for d in ids_docs
        ],
        "findings": findings,
        "action_plan": [
            "Review provisional title/inventorship deltas for new-matter and "
            "priority-support diligence (human).",
            "Confirm ISR + Written Opinion from PCT family were considered "
            "(IDS NPL cites present when export extracts match).",
            "PCT private IFW export incomplete — optional re-export with full "
            "Patent Center session if deeper PCT IFW inventory is needed.",
            "Optional: EPO OPS live foreign search remains separate from "
            "family/PCT diligence.",
        ],
        "disclaimer": GAP_CLOSURE_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }
    pack["pack_digest"] = _content_digest(pack)
    return pack


# ---------------------------------------------------------------------------
# Human diligence packs
# ---------------------------------------------------------------------------


def build_human_diligence_packs(
    application_number: str,
    *,
    state_root: Path | None = None,
    family_pack: Mapping[str, Any] | None = None,
    fetch_odp: bool = True,
) -> dict[str, Any]:
    """Build inventorship / new-matter / nonpublication / export evidence packs."""
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    bag = _load_full_application_bag(app, root)
    meta = bag.get("applicationMetaData") or {}
    if not isinstance(meta, Mapping):
        meta = {}
    pkg = resolve_export_package_dir(app, state_root=root)
    inventory = inventory_package_dir(pkg) if pkg else {"files": []}
    codes = _ifw_codes(inventory)
    docs = _ifw_summary_docs(app, root)
    doc_codes = {
        str(d.get("documentCode") or "").upper()
        for d in docs
        if d.get("documentCode")
    }
    all_codes = codes | doc_codes

    family = (
        dict(family_pack)
        if family_pack
        else build_family_pct_isr_pack(
            app, state_root=root, fetch_odp=fetch_odp
        )
    )

    inventors = _inventor_names(bag)
    title = str(meta.get("inventionTitle") or family.get("subject_title") or "")
    pub_data = bag.get("preGrantPublicationData") or []
    published = bool(pub_data) or "NTC.PUB" in all_codes
    pub_date = None
    pub_number = None
    if isinstance(pub_data, list) and pub_data and isinstance(pub_data[0], Mapping):
        pub_date = pub_data[0].get("publicationDate")
        y = pub_data[0].get("publicationYear")
        seq = pub_data[0].get("publicationSequenceNumber")
        if y and seq:
            pub_number = f"US{y}{seq}"

    status = str(meta.get("applicationStatusDescriptionText") or "")
    patented = bool(re.search(r"patent", status, re.I)) or bool(
        meta.get("patentNumber")
    )
    has_pct_child = bool(family.get("pct_children") or family.get("pct_odp"))

    packs: dict[str, Any] = {}

    # Inventorship
    inv_flags = [
        f
        for f in (family.get("findings") or [])
        if f.get("code") == "inventorship_delta_vs_provisional"
    ]
    packs["inventorship"] = {
        "item_id": "check:inventorship",
        "category": "inventorship",
        "authority": "35 U.S.C. § 115 / 37 C.F.R. § 1.63",
        "evidence": {
            "inventors_on_subject": inventors,
            "oath_present": "OATH" in all_codes,
            "ads_present": "ADS" in all_codes,
            "inventorship_delta_vs_provisional": inv_flags,
        },
        "machine_status": (
            "evidence_ready_human_confirm"
            if inventors and "OATH" in all_codes
            else "needs_review"
        ),
        "review_questions": [
            "Are all inventors who contributed to claimed subject matter listed?",
            "Was inventorship updated correctly if inventors were added after "
            "the provisional (delta flags)?",
            "Do oath/declaration signatures cover each inventor (human "
            "signature verification — not automated)?",
        ],
        "auto_confirm_allowed": False,
        "suggested_confirmation_note": (
            "OATH present and inventor bag non-empty; still requires natural-"
            "person confirmation of inventorship accuracy and signatures."
        ),
    }

    # New matter / priority support
    title_flags = [
        f
        for f in (family.get("findings") or [])
        if f.get("code") == "provisional_title_mismatch"
    ]
    packs["new_matter"] = {
        "item_id": "check:new-matter",
        "category": "new_matter",
        "authority": "35 U.S.C. § 132 / 35 U.S.C. §§ 119–120",
        "evidence": {
            "subject_title": title,
            "subject_filing_date": meta.get("filingDate"),
            "priority_or_effective": (
                (load_export_temporal_anchors(app, state_root=root) or {}).get(
                    "priority_date"
                )
            ),
            "provisional_parents": family.get("provisionals") or [],
            "provisional_title_mismatch_flags": title_flags,
            "spec_present": "SPEC" in all_codes,
            "claims_present": "CLM" in all_codes,
            "patented": patented,
            "patent_number": meta.get("patentNumber"),
        },
        "machine_status": (
            "flagged_title_mismatch" if title_flags else "evidence_ready_human_confirm"
        ),
        "review_questions": [
            "Does the provisional disclosure support the claimed subject matter "
            "and effective filing date asserted for each claim?",
            "If provisional title differs (facial-image vs tamper-evident), "
            "confirm the shared technical disclosure still supports priority — "
            "do not rely on title alone.",
            "For patented cases: grant does not eliminate the need to understand "
            "priority support for portfolio/continuation strategy.",
        ],
        "auto_confirm_allowed": False,
        "suggested_confirmation_note": (
            "Title mismatch between provisional and nonprovisional is a "
            "diligence flag only; human must compare disclosures."
            if title_flags
            else "No automatic title mismatch; still compare disclosures."
        ),
    }

    # Nonpublication
    packs["nonpublication"] = {
        "item_id": "check:nonpublication",
        "category": "nonpublication",
        "authority": "35 U.S.C. § 122(b)",
        "evidence": {
            "publication_notice_present": "NTC.PUB" in all_codes,
            "pre_grant_publication_data": pub_data if isinstance(pub_data, list) else [],
            "publication_date": pub_date,
            "publication_number_guess": pub_number,
            "published": published,
            "foreign_filing_pct_present": has_pct_child,
            "note": (
                "Publication notice / pre-grant publication data indicate the "
                "application published. A nonpublication request either was not "
                "made, was rescinded, or did not prevent publication."
                if published
                else "No publication signal found in export meta/IFW codes."
            ),
        },
        "machine_status": (
            "evidence_ready_human_confirm" if published else "needs_review"
        ),
        "review_questions": [
            "Was a nonpublication request filed, and if so was it proper given "
            "foreign filing plans?",
            "If PCT/foreign filing occurred, confirm nonpublication "
            "certifications were consistent (or rescinded) before foreign filing.",
        ],
        "auto_confirm_allowed": False,
        "suggested_confirmation_note": (
            "Publication evidence present; nonpublication diligence is historical "
            "review for portfolio completeness, not a reopening of formalities."
            if published
            else "Confirm nonpublication posture manually."
        ),
    }

    # Export control / foreign filing license
    packs["export_control"] = {
        "item_id": "check:export",
        "category": "export_control",
        "authority": "35 U.S.C. § 184 / foreign filing license practice",
        "evidence": {
            "pct_family_member": has_pct_child,
            "pct_children": family.get("pct_children") or [],
            "pct_odp_status": (family.get("pct_odp") or {}).get("status"),
            "pct_export_status": family.get("pct_export_status") or {},
            "filing_receipt_present": "APP.FILE.REC" in all_codes,
            "note": (
                "PCT family filing is evidence that foreign filing occurred; "
                "confirm foreign-filing license / export-control compliance was "
                "obtained or covered by license-on-filing-receipt practice "
                "(human legal review)."
                if has_pct_child
                else "No PCT/foreign family child detected in continuity bag."
            ),
        },
        "machine_status": (
            "evidence_ready_human_confirm" if has_pct_child else "needs_review"
        ),
        "review_questions": [
            "Was a foreign filing license in effect before any foreign/PCT filing?",
            "Does the filing receipt or petition record cover export authorization?",
            "Any ongoing export-control constraints on the technology?",
        ],
        "auto_confirm_allowed": False,
        "suggested_confirmation_note": (
            "PCT child exists — export/FFL diligence is material. Do not treat "
            "machine evidence as a license determination."
            if has_pct_child
            else "No PCT child detected; still confirm any other foreign filings."
        ),
    }

    # Signature remains always human
    packs["signature"] = {
        "item_id": "check:signature",
        "category": "signature",
        "authority": "35 U.S.C. § 115 / 37 C.F.R. § 1.63",
        "evidence": {
            "oath_present": "OATH" in all_codes,
            "note": "Signature verification is always natural-person only.",
        },
        "machine_status": "human_only",
        "review_questions": [
            "Verify each inventor oath/declaration signature is present and valid."
        ],
        "auto_confirm_allowed": False,
        "suggested_confirmation_note": "Never auto-confirmed.",
    }

    return {
        "schema": HUMAN_DILIGENCE_PACK_SCHEMA,
        "ok": True,
        "application_number": app,
        "packs": packs,
        "ifw_codes_sample": sorted(all_codes)[:80],
        "disclaimer": GAP_CLOSURE_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def confirm_human_diligence_items(
    packs_payload: Mapping[str, Any],
    *,
    item_ids: Sequence[str],
    acknowledger_name: str,
    notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Attach explicit human confirmations to diligence pack items.

    Does not invent legal conclusions — records who confirmed which item_id
    with optional per-item notes and a digest of the evidence pack.
    """
    ack = str(acknowledger_name or "").strip()
    if not ack:
        return {
            "ok": False,
            "error": "acknowledger_name required",
            "code": "acknowledger_required",
        }

    notes = dict(notes or {})
    wanted = {str(i).strip() for i in item_ids if str(i).strip()}
    # also accept category shortcuts
    alias = {
        "inventorship": "check:inventorship",
        "new-matter": "check:new-matter",
        "new_matter": "check:new-matter",
        "nonpublication": "check:nonpublication",
        "export": "check:export",
        "export_control": "check:export",
    }
    wanted = {alias.get(w, w) for w in wanted}

    packs = dict(packs_payload.get("packs") or {})
    confirmations: list[dict[str, Any]] = []
    now = utc_now_iso()
    for key, pack in packs.items():
        if not isinstance(pack, Mapping):
            continue
        iid = str(pack.get("item_id") or "")
        if iid not in wanted:
            continue
        if pack.get("auto_confirm_allowed") is True:
            # still require human name; never silent
            pass
        conf = {
            "item_id": iid,
            "category": pack.get("category") or key,
            "confirmed": True,
            "confirmed_by": ack,
            "confirmed_at_utc": now,
            "evidence_digest": _content_digest(
                {k: pack.get(k) for k in ("item_id", "evidence", "machine_status")}
            ),
            "note": notes.get(iid)
            or notes.get(key)
            or pack.get("suggested_confirmation_note")
            or "",
            "disclaimer": (
                "Human confirmation of diligence review only — not a legal "
                "certification suitable for filing without independent counsel "
                "judgment where required."
            ),
        }
        confirmations.append(conf)
        # mutate copy
        updated = dict(pack)
        updated["confirmation"] = conf
        packs[key] = updated

    missing = wanted - {c["item_id"] for c in confirmations}
    return {
        "ok": True,
        "schema": "patlaw-human-diligence-confirmations-v1",
        "application_number": packs_payload.get("application_number"),
        "acknowledger_name": ack,
        "confirmed_at_utc": now,
        "confirmations": confirmations,
        "missing_item_ids": sorted(missing),
        "packs": packs,
        "disclaimer": GAP_CLOSURE_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def close_application_gaps(
    application_number: str,
    *,
    state_root: Path | None = None,
    run_id: str | None = None,
    acknowledger_name: str = "operator:local",
    accept_foreign_gap_flag: bool = True,
    confirm_human_items: Sequence[str] | None = None,
    fetch_odp: bool = True,
    reaudit: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Close residual diligence gaps for one application and optionally re-audit.

    Parameters
    ----------
    accept_foreign_gap_flag:
        When True, write a formal foreign-gap *acceptance* (gap remains
        visible). Does not claim foreign was searched.
    confirm_human_items:
        Optional list of checklist item ids to mark confirmed with
        ``acknowledger_name`` (e.g. check:nonpublication). Never silent.
    """
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    if not app:
        return {"ok": False, "error": "application_number required"}

    ack = str(acknowledger_name or "operator:local").strip()
    run_path: Path | None = None
    if run_id:
        candidate = root / "prior_art" / app / str(run_id)
        if candidate.is_dir():
            run_path = candidate
    if run_path is None:
        run_path = _latest_prior_art_run(root, app)

    result: dict[str, Any] = {
        "schema": GAP_CLOSURE_SCHEMA,
        "ok": True,
        "application_number": app,
        "state_root": str(root),
        "prior_art_run": str(run_path) if run_path else None,
        "acknowledger_name": ack,
        "steps": {},
        "paths": {},
        "disclaimer": GAP_CLOSURE_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }

    # 1) Ensure foreign gap package exists
    foreign_pkg_result: dict[str, Any] = {"ok": False, "skipped": True}
    if run_path is not None:
        try:
            if not (run_path / "foreign_gap_package.json").is_file():
                foreign_pkg_result = build_and_persist_foreign_gap_package(
                    run_path, application_number=app
                )
            else:
                foreign_pkg_result = {
                    "ok": True,
                    "skipped": True,
                    "package_path": str(run_path / "foreign_gap_package.json"),
                }
        except Exception as exc:  # noqa: BLE001
            foreign_pkg_result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    result["steps"]["foreign_gap_package"] = foreign_pkg_result

    # 2) Formal foreign gap acceptance
    foreign_accept: dict[str, Any] = {
        "ok": False,
        "skipped": True,
        "reason": "disabled_or_no_run",
    }
    if accept_foreign_gap_flag and run_path is not None:
        foreign_accept = accept_foreign_gap(
            application_number=app,
            run_dir=run_path,
            acknowledger_name=ack,
        )
    result["steps"]["foreign_gap_acceptance"] = {
        k: v
        for k, v in foreign_accept.items()
        if k != "acceptance" or True
    }
    if foreign_accept.get("path"):
        result["paths"]["foreign_gap_acceptance"] = foreign_accept["path"]

    # 3) Family / PCT / ISR
    family_pack = build_family_pct_isr_pack(
        app, state_root=root, fetch_odp=fetch_odp
    )
    result["steps"]["family_pct_isr"] = {
        "ok": family_pack.get("ok"),
        "finding_codes": [f.get("code") for f in family_pack.get("findings") or []],
        "provisional_count": len(family_pack.get("provisionals") or []),
        "pct_child_count": len(family_pack.get("pct_children") or []),
        "isr_mentioned": (family_pack.get("isr_text_evidence") or {}).get(
            "isr_mentioned"
        ),
        "wo_mentioned": (family_pack.get("isr_text_evidence") or {}).get(
            "wo_mentioned"
        ),
    }

    # 4) Human diligence packs
    human_packs = build_human_diligence_packs(
        app, state_root=root, family_pack=family_pack, fetch_odp=fetch_odp
    )
    confirmations: dict[str, Any] | None = None
    if confirm_human_items:
        confirmations = confirm_human_diligence_items(
            human_packs,
            item_ids=list(confirm_human_items),
            acknowledger_name=ack,
        )
        if confirmations.get("packs"):
            human_packs = dict(human_packs)
            human_packs["packs"] = confirmations["packs"]
            human_packs["confirmations"] = confirmations.get("confirmations")
    result["steps"]["human_diligence"] = {
        "ok": human_packs.get("ok"),
        "pack_keys": list((human_packs.get("packs") or {}).keys()),
        "confirmed_item_ids": [
            c.get("item_id")
            for c in (human_packs.get("confirmations") or [])
            if c.get("confirmed")
        ],
    }

    # 5) Persist
    out_dir: Path | None = None
    if persist:
        stamp = utc_now_iso().replace(":", "").replace("-", "")[:15]
        out_dir = root / "compliance_audits" / app / f"gap_closure_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "dir": str(out_dir),
            "family_pct_isr": str(
                _write_json(out_dir / "family_pct_isr_pack.json", family_pack)
            ),
            "human_diligence": str(
                _write_json(out_dir / "human_diligence_packs.json", human_packs)
            ),
        }
        if foreign_accept.get("acceptance"):
            paths["foreign_gap_acceptance"] = str(
                _write_json(
                    out_dir / "foreign_gap_acceptance.json",
                    foreign_accept["acceptance"],
                )
            )
        # operator checklist snapshot with evidence bindings
        checklist = _build_gap_closure_checklist(
            human_packs,
            foreign_acceptance=foreign_accept.get("acceptance"),
            family_pack=family_pack,
        )
        paths["operator_checklist"] = str(
            _write_json(out_dir / "operator_checklist_gap_closure.json", checklist)
        )
        summary = {
            "schema": GAP_CLOSURE_SCHEMA,
            "application_number": app,
            "generated_at_utc": result["generated_at_utc"],
            "prior_art_run": result["prior_art_run"],
            "steps": result["steps"],
            "paths": paths,
            "checklist_summary": {
                "confirmed": [
                    i["item_id"]
                    for i in checklist.get("items") or []
                    if i.get("confirmed")
                ],
                "still_human": [
                    i["item_id"]
                    for i in checklist.get("items") or []
                    if not i.get("confirmed")
                ],
                "foreign_gap_accepted": bool(
                    foreign_accept.get("ok")
                    and foreign_accept.get("acceptance")
                ),
                "foreign_still_unsearched": True,
            },
            "action_plan": _gap_closure_action_plan(
                family_pack, human_packs, foreign_accept
            ),
            "disclaimer": GAP_CLOSURE_DISCLAIMER,
        }
        paths["summary"] = str(
            _write_json(out_dir / "gap_closure_summary.json", summary)
        )
        md = _render_gap_closure_markdown(summary, family_pack, human_packs)
        md_path = out_dir / "gap_closure_summary.md"
        md_path.write_text(md, encoding="utf-8")
        try:
            os.chmod(md_path, 0o600)
        except OSError:
            pass
        paths["markdown"] = str(md_path)
        result["paths"] = paths
        result["checklist"] = checklist
        result["action_plan"] = summary["action_plan"]
        # latest pointer
        try:
            _write_json(
                root / "exports" / "gap_closure_latest.json",
                {
                    "application_number": app,
                    "paths": paths,
                    "generated_at_utc": result["generated_at_utc"],
                },
            )
        except Exception:
            pass

    # 6) Re-audit
    if reaudit:
        try:
            from ipfs_datasets_py.processors.domains.uspto.application_rules_audit import (
                audit_application_rules,
            )

            audit = audit_application_rules(
                app,
                state_root=root,
                persist=persist,
            )
            result["steps"]["reaudit"] = {
                "ok": audit.get("ok"),
                "overall_status": audit.get("overall_status"),
                "severity_counts": audit.get("severity_counts"),
                "paths": audit.get("paths"),
                "operator_checklist_still_human": audit.get(
                    "operator_checklist_still_human"
                ),
                "operator_checklist_auto_confirmed": audit.get(
                    "operator_checklist_auto_confirmed"
                ),
            }
            if audit.get("paths"):
                result["paths"]["reaudit"] = audit["paths"]
        except Exception as exc:  # noqa: BLE001
            result["steps"]["reaudit"] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    result["family_pct_isr"] = family_pack
    result["human_diligence"] = human_packs
    result["foreign_gap_acceptance"] = foreign_accept.get("acceptance") or {
        k: foreign_accept.get(k)
        for k in ("ok", "skipped", "reason", "error", "message")
    }
    return result


def _build_gap_closure_checklist(
    human_packs: Mapping[str, Any],
    *,
    foreign_acceptance: Mapping[str, Any] | None,
    family_pack: Mapping[str, Any],
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.domains.uspto.filing_package import (
        default_mandatory_checklist,
    )

    items = [item.to_dict() for item in default_mandatory_checklist()]
    packs = human_packs.get("packs") or {}
    pack_by_id = {
        str(p.get("item_id")): p
        for p in packs.values()
        if isinstance(p, Mapping) and p.get("item_id")
    }
    # also include confirmations map
    conf_by_id = {}
    for c in human_packs.get("confirmations") or []:
        if isinstance(c, Mapping) and c.get("item_id"):
            conf_by_id[str(c["item_id"])] = c

    now = utc_now_iso()
    for item in items:
        iid = str(item.get("item_id") or "")
        pack = pack_by_id.get(iid) or {}
        conf = conf_by_id.get(iid) or (pack.get("confirmation") if pack else None)
        labels = dict(item.get("labels") or {})
        if pack:
            labels["evidence_machine_status"] = pack.get("machine_status")
            labels["gap_closure"] = True
            if pack.get("evidence"):
                labels["evidence_keys"] = sorted(
                    str(k) for k in (pack.get("evidence") or {}).keys()
                )
        if conf and conf.get("confirmed"):
            item["confirmed"] = True
            item["confirmed_by"] = conf.get("confirmed_by")
            item["confirmed_at_utc"] = conf.get("confirmed_at_utc") or now
            labels["confirmation_note"] = conf.get("note") or ""
            labels["confirmation_source"] = "human_diligence_pack"
        item["labels"] = labels

    # Foreign gap is not a checklist category but annotate IDS item
    for item in items:
        if item.get("item_id") == "check:ids" and foreign_acceptance:
            labels = dict(item.get("labels") or {})
            labels["foreign_gap_accepted"] = True
            labels["foreign_gap_remains_visible"] = bool(
                foreign_acceptance.get("gap_remains_visible", True)
            )
            labels["foreign_claims_coverage"] = False
            item["labels"] = labels

    # Family flags on priority/new-matter
    title_mismatch = any(
        f.get("code") == "provisional_title_mismatch"
        for f in (family_pack.get("findings") or [])
    )
    inv_delta = any(
        f.get("code") == "inventorship_delta_vs_provisional"
        for f in (family_pack.get("findings") or [])
    )
    for item in items:
        labels = dict(item.get("labels") or {})
        if item.get("item_id") == "check:new-matter" and title_mismatch:
            labels["provisional_title_mismatch"] = True
        if item.get("item_id") == "check:inventorship" and inv_delta:
            labels["inventorship_delta_vs_provisional"] = True
        item["labels"] = labels

    return {
        "schema": "patlaw-operator-checklist-gap-closure-v1",
        "application_number": human_packs.get("application_number"),
        "generated_at_utc": now,
        "items": items,
        "note": (
            "Confirmed items require explicit acknowledger via "
            "--confirm-human-items. Evidence labels are pre-filled from "
            "exports/ODP; they are not legal certifications. Foreign gap "
            "acceptance never asserts foreign coverage."
        ),
    }


def _gap_closure_action_plan(
    family_pack: Mapping[str, Any],
    human_packs: Mapping[str, Any],
    foreign_accept: Mapping[str, Any],
) -> list[str]:
    steps: list[str] = []
    if foreign_accept.get("ok") and foreign_accept.get("acceptance"):
        steps.append(
            "Foreign-patent named gap formally accepted with gap remaining "
            "visible — optional EPO OPS live search still available "
            "(EPO_OPS_KEY/EPO_OPS_SECRET + --live-foreign)."
        )
    elif foreign_accept.get("skipped"):
        steps.append(
            "Foreign gap acceptance skipped — run with --accept-foreign-gap "
            "or provide EPO credentials for a real foreign search."
        )
    for f in family_pack.get("findings") or []:
        if f.get("code") == "provisional_title_mismatch":
            steps.append(
                "Human: compare provisional vs nonprovisional disclosure for "
                "priority support (title mismatch: "
                f"{f.get('provisional_title')!r} vs {f.get('subject_title')!r})."
            )
        if f.get("code") == "inventorship_delta_vs_provisional":
            steps.append(
                "Human: confirm inventorship delta vs provisional "
                f"(added={f.get('added_on_subject')})."
            )
        if f.get("code") == "isr_wo_evidence_in_export":
            steps.append(
                "ISR/WO evidence present on IDS/REF.OTHER extracts — retain "
                "for family diligence; not a substitute for foreign corpus search."
            )
    confirmed = {
        c.get("item_id")
        for c in (human_packs.get("confirmations") or [])
        if c.get("confirmed")
    }
    still = [iid for iid in _HUMAN_ITEM_IDS if iid not in confirmed]
    if still:
        steps.append(
            "Human confirmations still open: "
            + ", ".join(still)
            + " (pass --confirm-human-items with acknowledger to record)."
        )
    steps.append(
        "Never Sign/Pay/Submit from automation; patented formalities remain "
        "historical record for portfolio diligence."
    )
    return steps


def _render_gap_closure_markdown(
    summary: Mapping[str, Any],
    family_pack: Mapping[str, Any],
    human_packs: Mapping[str, Any],
) -> str:
    lines = [
        f"# Application gap closure — {summary.get('application_number')}",
        "",
        f"**Generated:** {summary.get('generated_at_utc')}  ",
        f"**Prior-art run:** `{summary.get('prior_art_run')}`",
        "",
        summary.get("disclaimer") or GAP_CLOSURE_DISCLAIMER,
        "",
        "## Checklist summary",
        "",
    ]
    cs = summary.get("checklist_summary") or {}
    lines.append(
        f"- **Foreign gap accepted (still unsearched):** "
        f"{cs.get('foreign_gap_accepted')} / unsearched={cs.get('foreign_still_unsearched')}"
    )
    lines.append(
        f"- **Confirmed items:** {', '.join(cs.get('confirmed') or []) or '(none)'}"
    )
    lines.append(
        f"- **Still human:** {', '.join(cs.get('still_human') or []) or '(none)'}"
    )
    lines.extend(["", "## Family / PCT / ISR findings", ""])
    for f in family_pack.get("findings") or []:
        lines.append(
            f"- **{f.get('code')}** ({f.get('severity')}): {f.get('message')}"
        )
    lines.extend(["", "## Human diligence packs", ""])
    for key, pack in (human_packs.get("packs") or {}).items():
        if not isinstance(pack, Mapping):
            continue
        conf = pack.get("confirmation") or {}
        status = "CONFIRMED" if conf.get("confirmed") else pack.get("machine_status")
        lines.append(
            f"### {key} (`{pack.get('item_id')}`) — {status}"
        )
        lines.append("")
        lines.append(f"- Authority: {pack.get('authority')}")
        for q in pack.get("review_questions") or []:
            lines.append(f"- Review: {q}")
        lines.append("")
    ap = summary.get("action_plan") or []
    if ap:
        lines.extend(["## Action plan", ""])
        for i, step in enumerate(ap, 1):
            lines.append(f"{i}. {step}")
        lines.append("")
    return "\n".join(lines) + "\n"


def load_latest_gap_closure(
    application_number: str, *, state_root: Path | None = None
) -> dict[str, Any] | None:
    """Load the most recent gap_closure_* summary for an application."""
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    base = root / "compliance_audits" / app
    if not base.is_dir():
        return None
    dirs = sorted(
        [p for p in base.iterdir() if p.is_dir() and p.name.startswith("gap_closure_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        return None
    summary = _read_json(dirs[0] / "gap_closure_summary.json")
    if not summary:
        return None
    summary["_dir"] = str(dirs[0])
    # attach acceptance if present
    acc = _read_json(dirs[0] / "foreign_gap_acceptance.json")
    if acc:
        summary["foreign_gap_acceptance"] = acc
    human = _read_json(dirs[0] / "human_diligence_packs.json")
    if human:
        summary["human_diligence"] = human
    family = _read_json(dirs[0] / "family_pct_isr_pack.json")
    if family:
        summary["family_pct_isr"] = family
    return summary


def load_foreign_gap_acceptance_for_app(
    application_number: str, *, state_root: Path | None = None
) -> dict[str, Any] | None:
    """Find foreign gap acceptance on latest prior-art run or gap_closure dir."""
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    run = _latest_prior_art_run(root, app)
    if run and (run / "foreign_gap_acceptance.json").is_file():
        return _read_json(run / "foreign_gap_acceptance.json")
    latest = load_latest_gap_closure(app, state_root=root)
    if latest and latest.get("foreign_gap_acceptance"):
        return dict(latest["foreign_gap_acceptance"])
    return None


__all__ = [
    "FAMILY_PCT_PACK_SCHEMA",
    "FOREIGN_GAP_ACCEPTANCE_SCHEMA",
    "GAP_CLOSURE_DISCLAIMER",
    "GAP_CLOSURE_SCHEMA",
    "HUMAN_DILIGENCE_PACK_SCHEMA",
    "accept_foreign_gap",
    "build_family_pct_isr_pack",
    "build_human_diligence_packs",
    "close_application_gaps",
    "confirm_human_diligence_items",
    "fetch_odp_application_snapshot",
    "load_foreign_gap_acceptance_for_app",
    "load_latest_gap_closure",
]
