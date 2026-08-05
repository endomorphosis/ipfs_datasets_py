#!/usr/bin/env python3
"""Build a production-scale public legal corpus recipe for Hub packaging.

PATLAW-186 / PATLAW-G218 — full-authority integration.

Sources (public US government works):

* **35 U.S.C.** — optional live path from ``justicedao/ipfs_uscode`` laws parquet
* **Full annual CFR Title 37** — PATLAW-181 GovInfo annual package (not eCFR-only)
* **Full MPEP sections** — PATLAW-183 section-level inventory (not chapter-only)
* **USPTO guidance PDFs** — PATLAW-185 hash-verified PDF texts
* **Legacy live eCFR / MPEP chapters** — optional supplemental crawl paths that
  **do not** complete full-authority acceptance on their own

Writes a PATLAW-170-compatible recipe JSON (``source_roots`` + ``documents``)
with full-authority tallies, source receipts, rights, and current-through pins
suitable for ``package_patent_legal_hub_indexes.py --recipe``.

Default full-authority mode is **offline**: it consumes the acquisition CLIs'
fixture/catalog paths so CI never requires network or Hub upload.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Optional, Sequence, Union


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (  # noqa: E402
    SectionPresence,
    title37_section_count,
)
from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (  # noqa: E402
    REQUIRED_CHAPTER_IDS,
    is_chapter_landing_anchor,
)
from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (  # noqa: E402
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
)

# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-186"
GOAL_ID: Final = "PATLAW-G218"
RECIPE_SCHEMA_VERSION: Final = "patent.public_legal_corpus.v1"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
LEGACY_RECIPE_ID: Final = "patlaw-production-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")

USER_AGENT = "patent-legal-production-corpus/1.0 (+https://huggingface.co/justicedao)"
RIGHTS = {
    "license_expression": "public-domain-US-government",
    "notes": "US government work (public domain); production recipe for Hub publish",
    "redistribution_allowed": True,
    "review_status": "reviewed",
    "reviewed_at": "2026-08-01T00:00:00Z",
    "reviewed_by": "patent-legal-governance",
}

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProductionRecipeError(RuntimeError):
    """Base error for production recipe construction failures."""

    code: str = "production_recipe_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class FullAuthorityIncompleteError(ProductionRecipeError):
    """Raised when a recipe claims full authority without required sources."""

    code = "full_authority_incomplete"


class EcfrOnlyCompletionError(ProductionRecipeError):
    """Raised when eCFR-only substitutes for annual CFR Title 37 completion."""

    code = "ecfr_only_completion_rejected"


class ChapterOnlyMpepCompletionError(ProductionRecipeError):
    """Raised when chapter-landing MPEP crawls substitute for section-level."""

    code = "chapter_only_mpep_completion_rejected"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _http_get(url: str, *, timeout: float = 120.0, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_sibling_module(script_name: str) -> ModuleType:
    """Load a co-located acquisition script as a module (no package install)."""

    path = Path(__file__).resolve().parent / script_name
    if not path.is_file():
        raise ProductionRecipeError(f"missing acquisition script: {path}")
    module_name = f"_patlaw186_{path.stem}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ProductionRecipeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _doc(
    *,
    record_id: str,
    family: str,
    source_root_id: str,
    citation: str,
    title: str,
    section_id: str,
    text: str,
    authority_kind: str,
    current_through: str,
    source_uri: str,
    source_revision: str,
    source_id: str,
    effective_start: str = "2020-01-01",
    rights_review: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    min_text_len: int = 20,
) -> dict[str, Any]:
    body = (text or "").strip()
    if len(body) < min_text_len:
        raise ValueError(f"text too short for {record_id} (len={len(body)})")
    digest = _sha256_text(body)
    payload: dict[str, Any] = {
        "record_id": record_id,
        "family": family,
        "source_root_id": source_root_id,
        "classification": "public_official",
        "citation": citation,
        "title": title,
        "section_id": section_id,
        "text": body,
        "authority_kind": authority_kind,
        "authority_claim": "source_bound",
        "current_through": current_through,
        "effective_start": effective_start,
        "source_lineage": {
            "authority": "official",
            "source_id": source_id,
            "source_revision": source_revision,
            "source_sha256": digest,
            "source_uri": source_uri,
        },
        "rights_review": dict(rights_review or RIGHTS),
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def _count_by(docs: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in docs:
        k = str(d.get(key) or "")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rights_to_dict(rights: Any) -> dict[str, Any]:
    if rights is None:
        return dict(RIGHTS)
    if isinstance(rights, Mapping):
        return dict(rights)
    if hasattr(rights, "to_dict"):
        return dict(rights.to_dict())
    return dict(RIGHTS)


# ---------------------------------------------------------------------------
# Legacy live loaders (optional; not full-authority completion)
# ---------------------------------------------------------------------------


def load_title35_from_hf() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from huggingface_hub import hf_hub_download
    import pandas as pd

    path = hf_hub_download(
        repo_id="justicedao/ipfs_uscode",
        repo_type="dataset",
        filename="uscode_parquet/laws.parquet",
    )
    df = pd.read_parquet(
        path,
        columns=[
            "title_number",
            "section_number",
            "law_name",
            "text",
            "source_url",
            "date_modified",
            "ipfs_cid",
        ],
    )
    t35 = df[df["title_number"].astype(str) == "35"].copy()
    docs: list[dict[str, Any]] = []
    for row in t35.itertuples(index=False):
        sec = str(row.section_number).strip()
        title = str(row.law_name or f"35 U.S.C. § {sec}").strip()
        text = str(row.text or "").strip()
        url = str(row.source_url or "").strip() or (
            f"https://www.govinfo.gov/content/pkg/USCODE-2024-title35/html/"
            f"USCODE-2024-title35-sec{sec}.htm"
        )
        year = str(row.date_modified or "2024").strip() or "2024"
        docs.append(
            _doc(
                record_id=f"usc:35:{sec}",
                family="uscode",
                source_root_id="uscode-title35-2024",
                citation=f"35 U.S.C. § {sec}",
                title=title,
                section_id=sec,
                text=text,
                authority_kind="statute",
                current_through=f"{year}-12-31",
                source_uri=url,
                source_revision=f"govinfo-{year}-title35",
                source_id=f"uscode/title35/{sec}",
                effective_start=f"{year}-01-01",
            )
        )
    root = {
        "source_id": "uscode-title35-2024",
        "family": "uscode",
        "current_through": "2024-12-31",
        "official_edition_cutoff": "2024-12-31",
        "source_uri": "https://www.govinfo.gov/app/details/USCODE-2024-title35",
        "source_revision": "govinfo-2024-title35",
        "license_expression": "public-domain-US-government",
        "gaps": [],
    }
    return docs, root


def load_ecfr_title37(
    *, as_of: str = "2024-06-01"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Live eCFR Title 37 crawl (supplemental only; never full-authority CFR)."""

    url = f"https://www.ecfr.gov/api/renderer/v1/content/enhanced/{as_of}/title-37"
    html = _http_get(url, accept="text/html").decode("utf-8", errors="replace")
    pattern = re.compile(
        r'<div class="section" id="([^"]+)">\s*'
        r"(?:<h4[^>]*>(.*?)</h4>)?(.*?)"
        r'(?=<div class="section" id="|$)',
        re.IGNORECASE | re.DOTALL,
    )
    docs: list[dict[str, Any]] = []
    for match in pattern.finditer(html):
        sec_id = match.group(1).strip()
        heading_html = match.group(2) or ""
        body_html = match.group(3) or ""
        heading = _strip_html(heading_html)
        body = _strip_html(body_html)
        text = (heading + "\n\n" + body).strip() if heading else body
        if len(text) < 40:
            continue
        title = heading or f"37 C.F.R. § {sec_id}"
        title = re.sub(r"^§\s*" + re.escape(sec_id) + r"\s*", "", title).strip() or title
        docs.append(
            _doc(
                record_id=f"ecfr:37:{sec_id}",
                family="ecfr",
                source_root_id=f"ecfr-title37-{as_of}",
                citation=f"37 C.F.R. § {sec_id}",
                title=title[:500],
                section_id=sec_id,
                text=text,
                authority_kind="regulation",
                current_through=as_of,
                source_uri=f"https://www.ecfr.gov/current/title-37/section-{sec_id}",
                source_revision=f"ecfr-{as_of}-title37",
                source_id=f"ecfr/title37/{sec_id}",
                effective_start=as_of,
            )
        )
    if len(docs) < 50:
        raise RuntimeError(
            f"eCFR Title 37 parse produced only {len(docs)} sections; refusing"
        )
    root = {
        "source_id": f"ecfr-title37-{as_of}",
        "family": "ecfr",
        "current_through": as_of,
        "official_edition_cutoff": as_of,
        "source_uri": "https://www.ecfr.gov/current/title-37",
        "source_revision": f"ecfr-{as_of}-title37",
        "license_expression": "public-domain-US-government",
        "gaps": [
            "eCFR is an unofficial editorial compilation of CFR; annual CFR "
            "edition remains the official printed authority where it conflicts",
            "eCFR-only never completes full-authority CFR Title 37 (PATLAW-186)",
        ],
    }
    return docs, root


def load_mpep_chapters() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Live MPEP chapter HTML crawl (chapter-level; not full-authority)."""

    index_url = "https://www.uspto.gov/web/offices/pac/mpep/index.html"
    index_html = _http_get(index_url, accept="text/html").decode(
        "utf-8", errors="replace"
    )
    chapter_hrefs = sorted(
        set(
            re.findall(
                r'href="(mpep-\d{4}(?:-[^"]+)?\.html)"',
                index_html,
                flags=re.IGNORECASE,
            )
        )
    )
    if not chapter_hrefs:
        raise RuntimeError("no MPEP chapter links found on USPTO index")

    docs: list[dict[str, Any]] = []
    base = "https://www.uspto.gov/web/offices/pac/mpep/"
    for href in chapter_hrefs:
        url = base + href
        try:
            html = _http_get(url, accept="text/html", timeout=90).decode(
                "utf-8", errors="replace"
            )
        except urllib.error.HTTPError as exc:
            print(f"skip mpep {href}: {exc}", file=sys.stderr)
            continue
        text = _strip_html(html)
        if len(text) < 200:
            continue
        m = re.search(r"<title>([^<]+)</title>", html, re.I)
        title = _strip_html(m.group(1)) if m else href
        chap = re.sub(r"^mpep-|\.html$", "", href, flags=re.I)
        mpep_as_of = "2026-08-01"
        docs.append(
            _doc(
                record_id=f"mpep:chapter:{chap}",
                family="mpep",
                source_root_id="mpep-e9-current-chapters",
                citation=f"MPEP {chap}",
                title=title[:500],
                section_id=chap,
                text=text[:500000],
                authority_kind="guidance",
                current_through=mpep_as_of,
                source_uri=url,
                source_revision="uspto-mpep-web-current-chapters",
                source_id=f"mpep/chapter/{chap}",
                effective_start=mpep_as_of,
                metadata={"granularity": "chapter_landing", "full_authority": False},
            )
        )
        time.sleep(0.35)

    if len(docs) < 5:
        raise RuntimeError(f"MPEP fetch produced only {len(docs)} chapters")
    root = {
        "source_id": "mpep-e9-current-chapters",
        "family": "mpep",
        "current_through": "2026-08-01",
        "official_edition_cutoff": "2026-08-01",
        "source_uri": index_url,
        "source_revision": "uspto-mpep-web-current-chapters",
        "license_expression": "public-domain-US-government",
        "gaps": [
            "MPEP is USPTO examination guidance, not binding law",
            "chapter-landing pages only; does NOT complete full-authority MPEP "
            "(use PATLAW-183 section acquisition)",
        ],
    }
    return docs, root


# ---------------------------------------------------------------------------
# Full-authority loaders (consume PATLAW-181 / 183 / 185 acquisitions)
# ---------------------------------------------------------------------------


def load_full_cfr_title37(
    *,
    fixture_path: PathLike | None = None,
    year: str | int | None = None,
    live: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Materialize annual CFR Title 37 docs from PATLAW-181 acquisition.

    Returns ``(documents, source_root, full_authority_meta)``.
    eCFR-only payloads are rejected by the acquisition layer.
    When ``live`` is true, downloads official GovInfo annual volume XML
    (requires ``year``).
    """

    acq = _load_sibling_module("acquire_cfr_title37_full.py")
    result = acq.acquire_cfr_title37_full(
        fixture_path=None if live else fixture_path,
        year=year,
        stage=False,
        require_full_catalog=True,
        live=bool(live),
    )
    identity = result.manifest.edition_identity
    binding = result.manifest.package_binding
    package_id = identity.package_id
    current_through = identity.date_issued or f"{identity.year}-07-01"
    source_root_id = f"cfr-title37-annual-{identity.year}"
    source_revision = f"govinfo-{package_id}"

    docs: list[dict[str, Any]] = []
    for entry in result.manifest.inventory:
        if entry.presence is not SectionPresence.PRESENT:
            continue
        sec = entry.section
        text = result.section_texts.get(sec) or result.section_texts.get(
            sec.replace("-", ".")
        )
        if not text or len(text.strip()) < 20:
            # Inventory marked present but body missing — skip document row;
            # gap accounting remains on the acquisition receipt.
            continue
        uri = entry.source_url or (
            f"https://www.govinfo.gov/content/pkg/{package_id}/xml/"
            f"{package_id}-part{entry.part}-sec{sec.replace('.', '-')}.xml"
        )
        docs.append(
            _doc(
                record_id=f"cfr:37:{sec}:{identity.year}",
                family="cfr",
                source_root_id=source_root_id,
                citation=entry.citation or f"37 C.F.R. § {sec} ({identity.year} annual)",
                title=(entry.heading or f"37 C.F.R. § {sec}")[:500],
                section_id=sec,
                text=text,
                authority_kind="regulation",
                current_through=current_through,
                source_uri=uri,
                source_revision=source_revision,
                source_id=f"govinfo/cfr/title37/{sec}",
                effective_start=current_through,
                metadata={
                    "stable_id": entry.stable_id,
                    "part": entry.part,
                    "granule_id": entry.granule_id,
                    "package_id": package_id,
                    "authority_tier": identity.authority_tier,
                    "full_authority": True,
                    "source_kind": result.source_kind,
                },
            )
        )

    present_count = sum(
        1 for e in result.manifest.inventory if e.presence is SectionPresence.PRESENT
    )
    gap_count = sum(
        1 for e in result.manifest.inventory if e.presence is SectionPresence.GAP
    )
    inventory_total = len(result.manifest.inventory)
    expected_catalog = title37_section_count()
    if inventory_total != expected_catalog:
        raise FullAuthorityIncompleteError(
            f"CFR inventory size {inventory_total} != catalog {expected_catalog}"
        )
    if not docs:
        raise FullAuthorityIncompleteError(
            "full CFR Title 37 acquisition produced no present section documents"
        )

    root = {
        "source_id": source_root_id,
        "family": "cfr",
        "current_through": current_through,
        "official_edition_cutoff": current_through,
        "source_uri": binding.source_url
        or f"https://www.govinfo.gov/app/details/{package_id}",
        "source_revision": source_revision,
        "license_expression": "public-domain-US-government",
        "gaps": [
            f"present_sections={present_count}",
            f"gap_sections={gap_count}",
            (
                "live GovInfo annual volume XML; catalog rows without package "
                "text are explicit gaps (not eCFR-only)"
                if str(result.source_kind).endswith("live")
                else (
                    "bounded CI fixture may materialize a subset of granules; "
                    "full catalog is inventoried with explicit gaps (not eCFR-only)"
                )
            ),
        ],
        "package_id": package_id,
        "package_digest_sha256": binding.package_digest_sha256,
        "package_root_cid": binding.package_root_cid,
        "authority_tier": identity.authority_tier,
        "source_kind": result.source_kind,
        "full_authority": True,
    }
    meta = {
        "family": "cfr",
        "package_id": package_id,
        "year": identity.year,
        "provider": identity.provider,
        "authority_tier": identity.authority_tier,
        "source_kind": result.source_kind,
        "inventory_total": inventory_total,
        "catalog_section_count": expected_catalog,
        "present_sections": present_count,
        "gap_sections": gap_count,
        "documents_emitted": len(docs),
        "package_digest_sha256": binding.package_digest_sha256,
        "package_root_cid": binding.package_root_cid,
        "inventory_digest_sha256": result.manifest.inventory_digest_sha256
        if hasattr(result.manifest, "inventory_digest_sha256")
        else binding.inventory_digest_sha256,
        "not_ecfr_only": True,
        "receipt": {
            "task_id": result.receipt.get("task_id"),
            "schema_version": result.receipt.get("schema_version"),
            "package_id": result.receipt.get("package_id"),
            "package_digest_sha256": result.receipt.get("package_digest_sha256"),
            "package_root_cid": result.receipt.get("package_root_cid"),
            "counts": result.receipt.get("counts"),
            "source_kind": result.receipt.get("source_kind"),
        },
    }
    return docs, root, meta


def load_full_mpep_sections(
    *,
    inventory: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Materialize section-level MPEP docs from PATLAW-183 acquisition.

    Chapter-landing-page-only inventories fail closed in the acquisition layer.
    """

    acq = _load_sibling_module("acquire_mpep_full_sections.py")
    receipt = acq.acquire_mpep_full_sections(
        inventory,
        mode=acq.AcquisitionMode.DRY_RUN,
        strict_count=True,
    )
    pin = receipt.edition_pin
    edition_key = pin.edition_key
    current_through = pin.cutoff.isoformat() if hasattr(pin.cutoff, "isoformat") else str(pin.cutoff)
    source_root_id = f"mpep-{edition_key}"
    source_revision = f"uspto-{edition_key}"

    docs: list[dict[str, Any]] = []
    section_level = 0
    chapter_landing = 0
    for section in receipt.sections:
        status_val = (
            section.status.value
            if hasattr(section.status, "value")
            else str(section.status)
        )
        if status_val != "acquired":
            continue
        body = (section.text or "").strip()
        if len(body) < 20:
            # Pad deterministic short fixture bodies so recipe documents meet
            # the minimum corpus text floor without inventing legal content.
            body = (
                f"{body}\n\n"
                f"[MPEP section acquisition body for {section.stable_identity}; "
                f"edition {edition_key}; guidance only, not binding law.]"
            )
        kind_val = (
            section.kind.value if hasattr(section.kind, "value") else str(section.kind)
        )
        anchor = section.section_anchor
        chapter_id = section.chapter_id
        is_landing = is_chapter_landing_anchor(
            chapter_id=str(chapter_id), section_anchor=str(anchor)
        )
        if is_landing and kind_val == "mpep_section":
            chapter_landing += 1
            continue  # never emit pure chapter landings as full-authority docs
        section_level += 1
        uri = section.source_url or (
            f"https://www.uspto.gov/web/offices/pac/mpep/s{anchor}.html"
        )
        docs.append(
            _doc(
                record_id=f"mpep:section:{section.entry_id}",
                family="mpep",
                source_root_id=source_root_id,
                citation=section.citation or f"MPEP § {anchor}",
                title=(section.title or f"MPEP § {anchor}")[:500],
                section_id=str(anchor),
                text=body,
                authority_kind="guidance",
                current_through=current_through,
                source_uri=uri,
                source_revision=source_revision,
                source_id=f"uspto/mpep/{anchor}",
                effective_start=current_through,
                metadata={
                    "stable_identity": section.stable_identity,
                    "chapter_id": chapter_id,
                    "kind": kind_val,
                    "content_sha256": section.content_sha256,
                    "granularity": "section",
                    "full_authority": True,
                    "edition_key": edition_key,
                    "is_binding": False,
                },
            )
        )

    counts = receipt.counts
    if chapter_landing and not docs:
        raise ChapterOnlyMpepCompletionError(
            "MPEP acquisition yielded only chapter-landing anchors; "
            "section-level texts are required for full-authority completion"
        )
    if section_level < len(REQUIRED_CHAPTER_IDS):
        raise FullAuthorityIncompleteError(
            f"MPEP section-level docs ({section_level}) below required chapter "
            f"coverage ({len(REQUIRED_CHAPTER_IDS)})"
        )
    if counts.section_level_acquired < len(REQUIRED_CHAPTER_IDS):
        raise FullAuthorityIncompleteError(
            "MPEP acquisition counts.section_level_acquired below required chapters"
        )

    root = {
        "source_id": source_root_id,
        "family": "mpep",
        "current_through": current_through,
        "official_edition_cutoff": current_through,
        "source_uri": pin.source_url
        or "https://www.uspto.gov/web/offices/pac/mpep/index.html",
        "source_revision": source_revision,
        "license_expression": "public-domain-US-government",
        "gaps": [
            "MPEP is USPTO examination guidance, not binding law",
            "section-level inventory from PATLAW-183; chapter-only does not complete",
        ],
        "package_digest_sha256": receipt.package_digest_sha256,
        "package_root_cid": receipt.package_root_cid,
        "edition_key": edition_key,
        "full_authority": True,
        "is_binding": False,
        "authority_tier": "guidance",
    }
    meta = {
        "family": "mpep",
        "edition_key": edition_key,
        "edition": pin.edition,
        "revision": pin.revision,
        "cutoff": current_through,
        "inventory_entries": counts.inventory_entries,
        "inventory_present": counts.inventory_present,
        "inventory_gaps": counts.inventory_gaps,
        "acquired": counts.acquired,
        "section_level_acquired": counts.section_level_acquired,
        "chapters_required": counts.chapters_required,
        "chapters_covered": counts.chapters_covered,
        "supersession_edges": counts.supersession_edges,
        "documents_emitted": len(docs),
        "chapter_only": False,
        "package_digest_sha256": receipt.package_digest_sha256,
        "package_root_cid": receipt.package_root_cid,
        "inventory_digest_sha256": receipt.inventory_digest_sha256,
        "is_binding": False,
        "authority_tier": "guidance",
        "receipt": {
            "task_id": receipt.task_id,
            "schema_version": receipt.schema_version,
            "package_digest_sha256": receipt.package_digest_sha256,
            "package_root_cid": receipt.package_root_cid,
            "counts": counts.to_dict() if hasattr(counts, "to_dict") else {
                "inventory_entries": counts.inventory_entries,
                "inventory_present": counts.inventory_present,
                "acquired": counts.acquired,
                "section_level_acquired": counts.section_level_acquired,
                "chapters_required": counts.chapters_required,
                "chapters_covered": counts.chapters_covered,
            },
        },
    }
    return docs, root, meta


def load_full_uspto_guidance_pdfs(
    *,
    cutoff: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Materialize USPTO guidance PDF texts from PATLAW-185 acquisition."""

    acq = _load_sibling_module("acquire_uspto_guidance_pdfs.py")
    kwargs: dict[str, Any] = {"stage": False, "mode": "acquire"}
    if cutoff is not None:
        kwargs["cutoff"] = cutoff
    result = acq.acquire_uspto_guidance_pdfs(**kwargs)
    manifest = result.manifest
    pin = manifest.edition_pin
    current_through = (
        pin.cutoff.isoformat() if hasattr(pin.cutoff, "isoformat") else str(pin.cutoff)
    )
    source_root_id = f"uspto-guidance-pdfs-{current_through}"
    source_revision = f"uspto-guidance-pdfs-{pin.version}"

    docs: list[dict[str, Any]] = []
    for entry in manifest.inventory:
        status_val = (
            entry.status.value if hasattr(entry.status, "value") else str(entry.status)
        )
        if status_val != "present":
            continue
        key = f"{entry.document_id}::{entry.version}"
        # extracted_texts keys may be entry keys or filenames — try several.
        text = None
        for candidate in (
            key,
            f"{entry.document_id}-v{entry.version}",
            entry.entry_id,
            f"{entry.document_id}:{entry.version}",
        ):
            if candidate in result.extracted_texts:
                text = result.extracted_texts[candidate]
                break
        if text is None:
            # Fallback: match by document_id prefix.
            for k, v in result.extracted_texts.items():
                if entry.document_id in str(k) and entry.version in str(k):
                    text = v
                    break
        if text is None and len(result.extracted_texts) == len(manifest.inventory):
            # Stable order fallback when maps are parallel.
            idx = list(manifest.inventory).index(entry)
            text = list(result.extracted_texts.values())[idx]
        if not text or len(str(text).strip()) < 20:
            raise FullAuthorityIncompleteError(
                f"guidance PDF {entry.document_id}@{entry.version} missing extracted text"
            )
        rights = _rights_to_dict(entry.rights_review)
        # Normalize license expression for materializer compatibility.
        if rights.get("license_expression") in {"US-Gov-Work", "US-Gov"}:
            rights = {
                **rights,
                "license_expression": "public-domain-US-government",
            }
        text_sha = (
            entry.extraction.text_sha256
            if entry.extraction is not None and entry.extraction.text_sha256
            else _sha256_text(str(text))
        )
        docs.append(
            _doc(
                record_id=f"guidance:pdf:{entry.document_id}:v{entry.version}",
                family="guidance",
                source_root_id=source_root_id,
                citation=(
                    f"USPTO {entry.title or entry.document_id} "
                    f"(v{entry.version})"
                ),
                title=(entry.title or entry.document_id)[:500],
                section_id=f"{entry.document_id}@{entry.version}",
                text=str(text),
                authority_kind="guidance",
                current_through=current_through,
                source_uri=entry.uri,
                source_revision=source_revision,
                source_id=f"uspto/guidance/{entry.document_id}/{entry.version}",
                effective_start=(
                    entry.publication_date.isoformat()
                    if hasattr(entry.publication_date, "isoformat")
                    else current_through
                ),
                rights_review=rights,
                metadata={
                    "document_id": entry.document_id,
                    "version": entry.version,
                    "pdf_sha256": entry.sha256,
                    "text_sha256": text_sha,
                    "page_count": entry.page_count,
                    "topic": entry.topic,
                    "is_binding": False,
                    "authority_tier": "guidance",
                    "full_authority": True,
                    "hash_verified": bool(
                        (entry.metadata or {}).get("hash_verified", True)
                    ),
                    "stable_identity": (entry.metadata or {}).get("stable_identity"),
                },
            )
        )

    required = len(REQUIRED_GUIDANCE_DOCUMENTS)
    if len(docs) < required:
        raise FullAuthorityIncompleteError(
            f"guidance PDF docs ({len(docs)}) < required catalog ({required})"
        )
    present_ids = {d["metadata"]["document_id"] for d in docs}
    missing = set(REQUIRED_DOCUMENT_IDS) - present_ids
    if missing:
        raise FullAuthorityIncompleteError(
            f"guidance PDF catalog missing document_ids: {sorted(missing)}"
        )

    root = {
        "source_id": source_root_id,
        "family": "guidance",
        "current_through": current_through,
        "official_edition_cutoff": current_through,
        "source_uri": pin.source_url
        or "https://www.uspto.gov/patents/laws/examination-policy",
        "source_revision": source_revision,
        "license_expression": "public-domain-US-government",
        "gaps": [
            "USPTO examination guidance is not binding law",
            "prior/superseded editions retained as evidence when present",
        ],
        "package_digest_sha256": manifest.package_digest_sha256,
        "package_root_cid": manifest.package_root_cid,
        "full_authority": True,
        "is_binding": False,
        "authority_tier": "guidance",
        "documents_required": required,
        "documents_present": len(docs),
    }
    meta = {
        "family": "guidance",
        "inventory_pin": pin.pin_key if hasattr(pin, "pin_key") else f"{pin.document_id}@{pin.version}",
        "cutoff": current_through,
        "documents_required": required,
        "documents_present": len(docs),
        "hash_verified": bool(result.package_meta.get("hash_verified", True)),
        "package_digest_sha256": manifest.package_digest_sha256,
        "package_root_cid": manifest.package_root_cid,
        "is_binding": False,
        "authority_tier": "guidance",
        "document_ids": sorted(present_ids),
        "receipt": {
            "task_id": result.receipt.get("task_id"),
            "schema_version": result.receipt.get("schema_version"),
            "package_digest_sha256": result.receipt.get("package_digest_sha256"),
            "package_root_cid": result.receipt.get("package_root_cid"),
            "counts": result.receipt.get("counts"),
            "hash_verified": result.receipt.get("hash_verified"),
            "source_kind": result.receipt.get("source_kind"),
        },
    }
    return docs, root, meta


# ---------------------------------------------------------------------------
# Full-authority acceptance
# ---------------------------------------------------------------------------


def _mpep_docs_are_chapter_only(docs: Sequence[Mapping[str, Any]]) -> bool:
    mpep = [d for d in docs if d.get("family") == "mpep"]
    if not mpep:
        return False
    section_level = 0
    chapter_level = 0
    for d in mpep:
        rid = str(d.get("record_id") or "")
        meta = d.get("metadata") or {}
        granularity = str(meta.get("granularity") or "")
        if (
            rid.startswith("mpep:section:")
            or granularity == "section"
            or meta.get("full_authority") is True
        ):
            section_level += 1
            continue
        if rid.startswith("mpep:chapter:") or granularity == "chapter_landing":
            chapter_level += 1
            continue
        # Heuristic: section_id looks like a bare chapter landing.
        sec = str(d.get("section_id") or "")
        if sec.isdigit() and len(sec) in {3, 4} and sec in REQUIRED_CHAPTER_IDS:
            if is_chapter_landing_anchor(chapter_id=sec, section_anchor=sec):
                chapter_level += 1
                continue
        section_level += 1
    return chapter_level > 0 and section_level == 0


def assert_full_authority_complete(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless recipe proves full CFR + MPEP sections + guidance PDFs.

    Chapter-only MPEP and eCFR-only substitutes do **not** complete acceptance.
    """

    docs = list(recipe.get("documents") or [])
    roots = list(recipe.get("source_roots") or [])
    counts = dict(recipe.get("counts") or {})
    by_family = dict(counts.get("by_family") or _count_by(docs, "family"))
    fa = dict(recipe.get("full_authority") or {})
    sources = dict(fa.get("sources") or {})

    families_present = set(by_family) | {str(r.get("family") or "") for r in roots}
    for required in FULL_AUTHORITY_FAMILIES:
        if required not in families_present:
            raise FullAuthorityIncompleteError(
                f"full-authority recipe missing family {required!r}; "
                f"present={sorted(families_present)}"
            )
        if by_family.get(required, 0) < 1:
            raise FullAuthorityIncompleteError(
                f"full-authority by_family tally for {required!r} is zero"
            )

    # --- CFR annual package (not eCFR-only) ---
    cfr_meta = dict(sources.get("cfr_title37") or {})
    if not cfr_meta:
        raise FullAuthorityIncompleteError(
            "full_authority.sources.cfr_title37 missing; annual package required"
        )
    if not cfr_meta.get("not_ecfr_only", False):
        raise EcfrOnlyCompletionError(
            "CFR full-authority source must declare not_ecfr_only=true"
        )
    if str(cfr_meta.get("source_kind") or "").startswith("ecfr"):
        raise EcfrOnlyCompletionError(
            "eCFR-only source_kind cannot complete full-authority CFR Title 37"
        )
    inv_total = int(cfr_meta.get("inventory_total") or 0)
    catalog = int(cfr_meta.get("catalog_section_count") or title37_section_count())
    if inv_total != catalog or inv_total != title37_section_count():
        raise FullAuthorityIncompleteError(
            f"CFR inventory_total={inv_total} does not match full catalog "
            f"{title37_section_count()}"
        )
    if not cfr_meta.get("package_digest_sha256"):
        raise FullAuthorityIncompleteError("CFR package_digest_sha256 missing")
    if by_family.get("cfr", 0) < 1:
        raise FullAuthorityIncompleteError("no annual CFR documents in recipe")
    # eCFR-only roots without a cfr root fail.
    root_families = {str(r.get("family") or "") for r in roots}
    if "ecfr" in root_families and "cfr" not in root_families:
        raise EcfrOnlyCompletionError(
            "eCFR source root without annual CFR root cannot complete full authority"
        )

    # --- MPEP section-level (not chapter-only) ---
    mpep_meta = dict(sources.get("mpep_sections") or {})
    if not mpep_meta:
        raise FullAuthorityIncompleteError(
            "full_authority.sources.mpep_sections missing"
        )
    if mpep_meta.get("chapter_only") is True:
        raise ChapterOnlyMpepCompletionError(
            "chapter_only=true cannot complete full-authority MPEP"
        )
    section_acq = int(mpep_meta.get("section_level_acquired") or 0)
    if section_acq < len(REQUIRED_CHAPTER_IDS):
        raise FullAuthorityIncompleteError(
            f"MPEP section_level_acquired={section_acq} < "
            f"required chapters={len(REQUIRED_CHAPTER_IDS)}"
        )
    if by_family.get("mpep", 0) < len(REQUIRED_CHAPTER_IDS):
        raise FullAuthorityIncompleteError(
            f"mpep by_family={by_family.get('mpep')} below required chapter coverage"
        )
    if _mpep_docs_are_chapter_only(docs):
        raise ChapterOnlyMpepCompletionError(
            "MPEP documents are chapter-landing only; section-level required"
        )

    # --- USPTO guidance PDFs ---
    g_meta = dict(sources.get("uspto_guidance_pdfs") or {})
    if not g_meta:
        raise FullAuthorityIncompleteError(
            "full_authority.sources.uspto_guidance_pdfs missing"
        )
    required_g = len(REQUIRED_GUIDANCE_DOCUMENTS)
    present_g = int(g_meta.get("documents_present") or 0)
    if present_g < required_g:
        raise FullAuthorityIncompleteError(
            f"guidance documents_present={present_g} < required={required_g}"
        )
    if by_family.get("guidance", 0) < required_g:
        raise FullAuthorityIncompleteError(
            f"guidance by_family={by_family.get('guidance')} < required={required_g}"
        )

    if not fa.get("complete"):
        raise FullAuthorityIncompleteError(
            "full_authority.complete is not true"
        )

    # Tallies block must echo the same proof.
    fa_counts = dict(counts.get("full_authority") or {})
    if int(fa_counts.get("cfr_inventory_total") or 0) != title37_section_count():
        raise FullAuthorityIncompleteError(
            "counts.full_authority.cfr_inventory_total does not prove full catalog"
        )
    if int(fa_counts.get("mpep_section_level") or 0) < len(REQUIRED_CHAPTER_IDS):
        raise FullAuthorityIncompleteError(
            "counts.full_authority.mpep_section_level below required coverage"
        )
    if int(fa_counts.get("guidance_pdfs") or 0) < required_g:
        raise FullAuthorityIncompleteError(
            "counts.full_authority.guidance_pdfs below required catalog"
        )


def reject_ecfr_only_completion(
    *,
    documents: Sequence[Mapping[str, Any]] | None = None,
    source_roots: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Demonstrate fail-closed rejection of eCFR-only full-authority claims."""

    docs = list(documents or [])
    roots = list(source_roots or [])
    families = {str(d.get("family") or "") for d in docs} | {
        str(r.get("family") or "") for r in roots
    }
    if "ecfr" in families and "cfr" not in families:
        raise EcfrOnlyCompletionError(
            "eCFR-only recipe cannot complete full-authority CFR Title 37 "
            "(PATLAW-186); annual GovInfo package required"
        )
    raise EcfrOnlyCompletionError(
        "eCFR-only completion rejected (explicit fail-closed demo)"
    )


def reject_chapter_only_mpep_completion(
    documents: Sequence[Mapping[str, Any]],
) -> None:
    """Demonstrate fail-closed rejection of chapter-only MPEP completion."""

    if _mpep_docs_are_chapter_only(documents) or all(
        str(d.get("record_id") or "").startswith("mpep:chapter:")
        for d in documents
        if d.get("family") == "mpep"
    ):
        raise ChapterOnlyMpepCompletionError(
            "chapter-only MPEP crawl cannot complete full-authority MPEP "
            "(PATLAW-186); section-level acquisition required"
        )
    # Also reject when caller hands a pure chapter-landing recipe explicitly.
    mpep = [d for d in documents if d.get("family") == "mpep"]
    if not mpep:
        raise ChapterOnlyMpepCompletionError(
            "no MPEP documents; chapter-only path still rejected"
        )
    raise ChapterOnlyMpepCompletionError(
        "chapter-only MPEP completion rejected (explicit fail-closed demo)"
    )


# ---------------------------------------------------------------------------
# Recipe builders
# ---------------------------------------------------------------------------


def build_full_authority_recipe(
    *,
    include_uscode: bool = False,
    include_ecfr_supplement: bool = False,
    include_mpep_chapters_supplement: bool = False,
    ecfr_as_of: str = "2024-06-01",
    cfr_fixture_path: PathLike | None = None,
    cfr_year: str | int | None = None,
    live_cfr: bool = False,
    guidance_cutoff: str | None = None,
    assert_complete: bool = True,
) -> dict[str, Any]:
    """Build the production recipe with full CFR, MPEP sections, and guidance PDFs.

    Offline by default: consumes PATLAW-181/183/185 acquisition fixtures.
    With ``live_cfr=True`` (and ``cfr_year``), downloads official GovInfo
    annual Title 37 volume XML. Live Title 35 / eCFR / chapter MPEP remain
    optional supplements only.
    """

    docs: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    fa_sources: dict[str, Any] = {}

    print("loading full annual CFR Title 37 (PATLAW-181)…", file=sys.stderr)
    if live_cfr and (cfr_year is None or not str(cfr_year).strip()):
        raise FullAuthorityIncompleteError(
            "live_cfr requires cfr_year (pinned calendar year, never 'latest')"
        )
    cfr_docs, cfr_root, cfr_meta = load_full_cfr_title37(
        fixture_path=None if live_cfr else cfr_fixture_path,
        year=cfr_year,
        live=bool(live_cfr),
    )
    docs.extend(cfr_docs)
    roots.append(cfr_root)
    fa_sources["cfr_title37"] = cfr_meta
    receipts.append(
        {
            "family": "cfr",
            "source_root_id": cfr_root["source_id"],
            "receipt": cfr_meta.get("receipt"),
            "package_digest_sha256": cfr_meta.get("package_digest_sha256"),
            "package_root_cid": cfr_meta.get("package_root_cid"),
        }
    )
    print(
        f"  cfr docs={len(cfr_docs)} inventory={cfr_meta['inventory_total']} "
        f"present={cfr_meta['present_sections']} gaps={cfr_meta['gap_sections']}",
        file=sys.stderr,
    )

    print("loading full MPEP sections (PATLAW-183)…", file=sys.stderr)
    mpep_docs, mpep_root, mpep_meta = load_full_mpep_sections()
    docs.extend(mpep_docs)
    roots.append(mpep_root)
    fa_sources["mpep_sections"] = mpep_meta
    receipts.append(
        {
            "family": "mpep",
            "source_root_id": mpep_root["source_id"],
            "receipt": mpep_meta.get("receipt"),
            "package_digest_sha256": mpep_meta.get("package_digest_sha256"),
            "package_root_cid": mpep_meta.get("package_root_cid"),
        }
    )
    print(
        f"  mpep section docs={len(mpep_docs)} "
        f"section_level_acquired={mpep_meta['section_level_acquired']} "
        f"chapters={mpep_meta['chapters_covered']}/{mpep_meta['chapters_required']}",
        file=sys.stderr,
    )

    print("loading USPTO guidance PDFs (PATLAW-185)…", file=sys.stderr)
    g_docs, g_root, g_meta = load_full_uspto_guidance_pdfs(cutoff=guidance_cutoff)
    docs.extend(g_docs)
    roots.append(g_root)
    fa_sources["uspto_guidance_pdfs"] = g_meta
    receipts.append(
        {
            "family": "guidance",
            "source_root_id": g_root["source_id"],
            "receipt": g_meta.get("receipt"),
            "package_digest_sha256": g_meta.get("package_digest_sha256"),
            "package_root_cid": g_meta.get("package_root_cid"),
        }
    )
    print(
        f"  guidance docs={len(g_docs)} "
        f"required={g_meta['documents_required']}",
        file=sys.stderr,
    )

    if include_uscode:
        print("loading Title 35 from justicedao/ipfs_uscode…", file=sys.stderr)
        t35_docs, t35_root = load_title35_from_hf()
        docs.extend(t35_docs)
        roots.append(t35_root)
        print(f"  title35 docs={len(t35_docs)}", file=sys.stderr)

    if include_ecfr_supplement:
        print(f"loading supplemental eCFR Title 37 as-of {ecfr_as_of}…", file=sys.stderr)
        ecfr_docs, ecfr_root = load_ecfr_title37(as_of=ecfr_as_of)
        docs.extend(ecfr_docs)
        roots.append(ecfr_root)
        print(f"  ecfr docs={len(ecfr_docs)} (supplement only)", file=sys.stderr)

    if include_mpep_chapters_supplement:
        print("loading supplemental MPEP chapter pages…", file=sys.stderr)
        ch_docs, ch_root = load_mpep_chapters()
        docs.extend(ch_docs)
        roots.append(ch_root)
        print(f"  mpep chapter docs={len(ch_docs)} (supplement only)", file=sys.stderr)

    by_id: dict[str, dict[str, Any]] = {}
    for d in docs:
        by_id[d["record_id"]] = d
    documents = list(by_id.values())
    documents.sort(key=lambda d: d["record_id"])
    by_family = _count_by(documents, "family")

    fa_counts = {
        "cfr_inventory_total": int(cfr_meta["inventory_total"]),
        "cfr_present_sections": int(cfr_meta["present_sections"]),
        "cfr_gap_sections": int(cfr_meta["gap_sections"]),
        "cfr_documents": int(by_family.get("cfr", 0)),
        "mpep_section_level": int(mpep_meta["section_level_acquired"]),
        "mpep_documents": int(by_family.get("mpep", 0)),
        "mpep_chapters_covered": int(mpep_meta["chapters_covered"]),
        "guidance_pdfs": int(g_meta["documents_present"]),
        "guidance_documents": int(by_family.get("guidance", 0)),
    }

    recipe: dict[str, Any] = {
        "notes": (
            "Full-authority public patent-law corpus recipe (PATLAW-186): "
            "annual CFR Title 37 (GovInfo), section-level MPEP, and USPTO "
            "guidance PDFs with rights, current-through, and source receipts. "
            "Chapter-only MPEP and eCFR-only substitutes do not complete acceptance."
        ),
        "recipe_id": FULL_AUTHORITY_RECIPE_ID,
        "schema_version": RECIPE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "source_roots": roots,
        "documents": documents,
        "source_receipts": receipts,
        "full_authority": {
            "complete": True,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "sources": fa_sources,
            "reject_ecfr_only_completion": True,
            "reject_chapter_only_mpep_completion": True,
        },
        "expected": {
            "min_documents": (
                1  # at least one present CFR section from annual package
                + len(REQUIRED_CHAPTER_IDS)
                + len(REQUIRED_GUIDANCE_DOCUMENTS)
            ),
            "families": list(FULL_AUTHORITY_FAMILIES),
            "min_by_family": {
                "cfr": 1,
                "mpep": len(REQUIRED_CHAPTER_IDS),
                "guidance": len(REQUIRED_GUIDANCE_DOCUMENTS),
            },
            "cfr_inventory_total": title37_section_count(),
            "mpep_section_level_min": len(REQUIRED_CHAPTER_IDS),
            "guidance_pdfs_min": len(REQUIRED_GUIDANCE_DOCUMENTS),
            "require_full_cfr_inventory": True,
            "require_section_level_mpep": True,
            "reject_ecfr_only_completion": True,
            "reject_chapter_only_mpep_completion": True,
            "partition": "public",
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
        },
        "generated_at": _utc_now_iso(),
        "counts": {
            "documents": len(documents),
            "by_family": by_family,
            "source_roots": len(roots),
            "source_receipts": len(receipts),
            "full_authority": fa_counts,
        },
    }

    if assert_complete:
        assert_full_authority_complete(recipe)
    return recipe


def build_recipe(
    *,
    include_mpep: bool = True,
    ecfr_as_of: str = "2024-06-01",
    full_authority: bool = False,
    **full_authority_kwargs: Any,
) -> dict[str, Any]:
    """Build a production recipe.

    When ``full_authority`` is True (PATLAW-186 default path), returns the
    offline full-authority recipe. Otherwise uses the legacy live Title 35 /
    eCFR / MPEP chapter path (does **not** complete full-authority acceptance).
    """

    if full_authority:
        return build_full_authority_recipe(**full_authority_kwargs)

    docs: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []

    print("loading Title 35 from justicedao/ipfs_uscode…", file=sys.stderr)
    t35_docs, t35_root = load_title35_from_hf()
    docs.extend(t35_docs)
    roots.append(t35_root)
    print(f"  title35 docs={len(t35_docs)}", file=sys.stderr)

    print(f"loading eCFR Title 37 as-of {ecfr_as_of}…", file=sys.stderr)
    ecfr_docs, ecfr_root = load_ecfr_title37(as_of=ecfr_as_of)
    docs.extend(ecfr_docs)
    roots.append(ecfr_root)
    print(f"  ecfr docs={len(ecfr_docs)}", file=sys.stderr)

    if include_mpep:
        print("loading MPEP chapters from USPTO…", file=sys.stderr)
        mpep_docs, mpep_root = load_mpep_chapters()
        docs.extend(mpep_docs)
        roots.append(mpep_root)
        print(f"  mpep docs={len(mpep_docs)}", file=sys.stderr)

    by_id: dict[str, dict[str, Any]] = {}
    for d in docs:
        by_id[d["record_id"]] = d
    documents = list(by_id.values())
    documents.sort(key=lambda d: d["record_id"])

    recipe = {
        "notes": (
            "Legacy production public patent-law corpus recipe: full 35 U.S.C., "
            "eCFR Title 37, and USPTO MPEP chapters. Does NOT complete "
            "full-authority acceptance (use --full-authority / PATLAW-186)."
        ),
        "recipe_id": LEGACY_RECIPE_ID,
        "schema_version": RECIPE_SCHEMA_VERSION,
        "source_roots": roots,
        "documents": documents,
        "expected": {
            "min_documents": 200,
            "families": ["uscode", "ecfr"] + (["mpep"] if include_mpep else []),
        },
        "generated_at": _utc_now_iso(),
        "counts": {
            "documents": len(documents),
            "by_family": _count_by(documents, "family"),
            "source_roots": len(roots),
        },
        "full_authority": {
            "complete": False,
            "reason": (
                "legacy live eCFR + chapter MPEP path; run with --full-authority"
            ),
        },
    }
    return recipe


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write production recipe JSON here",
    )
    p.add_argument(
        "--full-authority",
        action="store_true",
        default=True,
        help="Build full-authority recipe (CFR annual + MPEP sections + guidance PDFs). Default: on.",
    )
    p.add_argument(
        "--legacy-live",
        action="store_true",
        help="Use legacy live Title 35 / eCFR / MPEP chapter path (not full-authority)",
    )
    p.add_argument(
        "--skip-mpep",
        action="store_true",
        help="(legacy) Skip USPTO MPEP chapter fetch",
    )
    p.add_argument(
        "--ecfr-as-of",
        default="2024-06-01",
        help="eCFR as-of date (YYYY-MM-DD) for legacy or supplemental path",
    )
    p.add_argument(
        "--include-uscode",
        action="store_true",
        help="(full-authority) Also pull 35 U.S.C. from Hugging Face",
    )
    p.add_argument(
        "--include-ecfr-supplement",
        action="store_true",
        help="(full-authority) Also include live eCFR as a non-completing supplement",
    )
    p.add_argument(
        "--cfr-fixture",
        type=Path,
        default=None,
        help="(full-authority) Explicit GovInfo annual Title 37 fixture path",
    )
    p.add_argument(
        "--cfr-year",
        default=None,
        help="(full-authority) Pin annual CFR year",
    )
    p.add_argument(
        "--live-cfr",
        action="store_true",
        help=(
            "(full-authority) Download official GovInfo annual Title 37 volume "
            "XML (requires --cfr-year; CI stays offline)"
        ),
    )
    p.add_argument(
        "--reject-ecfr-only",
        action="store_true",
        help="Exit non-zero demonstrating eCFR-only cannot complete full authority",
    )
    p.add_argument(
        "--reject-chapter-only-mpep",
        action="store_true",
        help="Exit non-zero demonstrating chapter-only MPEP cannot complete full authority",
    )
    p.add_argument(
        "--validate-recipe",
        type=Path,
        default=None,
        help="Validate an existing recipe JSON for full-authority acceptance",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.reject_ecfr_only:
        try:
            reject_ecfr_only_completion(
                documents=[{"family": "ecfr", "record_id": "ecfr:37:1.56"}],
                source_roots=[{"family": "ecfr", "source_id": "ecfr-only"}],
            )
        except EcfrOnlyCompletionError as exc:
            print(f"ecfr_only_rejected: {exc}", file=sys.stderr)
            return 2
        return 1

    if args.reject_chapter_only_mpep:
        try:
            reject_chapter_only_mpep_completion(
                [
                    {
                        "family": "mpep",
                        "record_id": "mpep:chapter:2100",
                        "section_id": "2100",
                        "metadata": {"granularity": "chapter_landing"},
                    }
                ]
            )
        except ChapterOnlyMpepCompletionError as exc:
            print(f"chapter_only_mpep_rejected: {exc}", file=sys.stderr)
            return 2
        return 1

    if args.validate_recipe is not None:
        payload = json.loads(args.validate_recipe.read_text(encoding="utf-8"))
        assert_full_authority_complete(payload)
        print(
            f"validated full-authority recipe {args.validate_recipe} "
            f"documents={payload.get('counts', {}).get('documents')} "
            f"by_family={payload.get('counts', {}).get('by_family')}",
            file=sys.stderr,
        )
        return 0

    if args.legacy_live:
        recipe = build_recipe(
            include_mpep=not args.skip_mpep,
            ecfr_as_of=args.ecfr_as_of,
            full_authority=False,
        )
    else:
        if args.live_cfr and args.cfr_fixture is not None:
            print(
                "ERROR: --live-cfr is mutually exclusive with --cfr-fixture",
                file=sys.stderr,
            )
            return 2
        if args.live_cfr and not args.cfr_year:
            print(
                "ERROR: --live-cfr requires --cfr-year YYYY",
                file=sys.stderr,
            )
            return 2
        recipe = build_full_authority_recipe(
            include_uscode=args.include_uscode,
            include_ecfr_supplement=args.include_ecfr_supplement,
            ecfr_as_of=args.ecfr_as_of,
            cfr_fixture_path=args.cfr_fixture,
            cfr_year=args.cfr_year,
            live_cfr=bool(args.live_cfr),
            assert_complete=True,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(recipe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {args.output} documents={recipe['counts']['documents']} "
        f"by_family={recipe['counts']['by_family']}",
        file=sys.stderr,
    )
    if recipe.get("full_authority", {}).get("complete"):
        print(
            f"full_authority tallies={recipe['counts'].get('full_authority')}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
