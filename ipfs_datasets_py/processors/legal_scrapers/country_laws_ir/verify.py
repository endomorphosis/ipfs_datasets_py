"""Admission verifiers for country-law normalization, before GraphRAG.

Oregon-style structure is preferred but not required for every gazette.
Verifiers fail closed on invented text, residual HTML, empty corpora, and
duplicate CIDs. Missing title/section hierarchy is a warning unless the
corpus already split into articles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

import pandas as pd

from .structure import has_html_tags

SCHEMA_VERSION = "country-laws-normalize-verify/v1"

_HTML_FAIL_FRACTION = 0.02
_SHORT_BODY_FAIL_FRACTION = 0.50
_MIN_BODY_CHARS = 40


@dataclass(frozen=True)
class Check:
    id: str
    severity: str  # fail | warn
    passed: bool
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bodies(corpus: pd.DataFrame) -> list[str]:
    if corpus is None or corpus.empty or "body" not in corpus.columns:
        return []
    return [str(x or "") for x in corpus["body"].tolist()]


def check_nonempty(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    n = int(len(corpus)) if corpus is not None else 0
    return Check(
        id="nonempty_corpus",
        severity="fail",
        passed=n > 0,
        message="normalized corpus has rows" if n else "normalized corpus is empty",
        evidence={"n_out": n, "n_dropped": report.get("n_dropped_total")},
    )


def check_entry_cids(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    if corpus is None or corpus.empty:
        return Check(
            id="entry_cid_unique",
            severity="fail",
            passed=False,
            message="no entry_cid values to verify",
            evidence={},
        )
    missing = int(corpus["entry_cid"].isna().sum()) if "entry_cid" in corpus.columns else int(len(corpus))
    dupes = int(corpus["entry_cid"].duplicated().sum()) if "entry_cid" in corpus.columns else 0
    empty = int((corpus["entry_cid"].astype(str).str.strip() == "").sum()) if "entry_cid" in corpus.columns else 0
    ok = missing == 0 and dupes == 0 and empty == 0
    return Check(
        id="entry_cid_unique",
        severity="fail",
        passed=ok,
        message="every row has a unique entry_cid" if ok else "missing or duplicate entry_cid",
        evidence={"missing": missing, "empty": empty, "duplicate": dupes},
    )


def check_no_invented_text(report: dict[str, Any]) -> Check:
    flag = bool(report.get("never_invented_legal_text", False))
    return Check(
        id="never_invented_legal_text",
        severity="fail",
        passed=flag,
        message="normalizer did not invent legal text" if flag else "invented-text flag is false",
        evidence={"never_invented_legal_text": flag},
    )


def check_html_residual(corpus: pd.DataFrame) -> Check:
    bodies = _bodies(corpus)
    tagged = [b for b in bodies if has_html_tags(b)]
    n = len(bodies) or 1
    fraction = len(tagged) / float(n)
    passed = fraction <= _HTML_FAIL_FRACTION
    return Check(
        id="html_residual",
        severity="fail",
        passed=passed,
        message=(
            "HTML tags stripped from legal bodies"
            if passed
            else f"{len(tagged)}/{len(bodies)} bodies still contain HTML tags"
        ),
        evidence={
            "n_bodies": len(bodies),
            "n_with_tags": len(tagged),
            "fraction": fraction,
            "samples": [b[:120] for b in tagged[:5]],
        },
    )


def check_short_bodies(corpus: pd.DataFrame) -> Check:
    bodies = _bodies(corpus)
    if not bodies:
        return Check(
            id="short_bodies",
            severity="fail",
            passed=False,
            message="no bodies to measure",
            evidence={},
        )
    short = sum(1 for b in bodies if len(b) < _MIN_BODY_CHARS)
    fraction = short / float(len(bodies))
    passed = fraction <= _SHORT_BODY_FAIL_FRACTION
    return Check(
        id="short_bodies",
        severity="fail" if not passed else "warn",
        passed=passed,
        message=(
            "most legal units have usable body length"
            if passed
            else f"{short}/{len(bodies)} bodies shorter than {_MIN_BODY_CHARS} characters"
        ),
        evidence={"n_short": short, "n_bodies": len(bodies), "fraction": fraction},
    )


def check_heading_language(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    """Warn when Latin heading dialect disagrees with the document language."""
    from .profiles import NO_LATIN_SPLIT_LANGS, iso_lang

    doc_lang = iso_lang(report.get("document_language_majority") or "")
    head_lang = iso_lang(report.get("heading_language_majority") or "")
    counts = report.get("heading_language_counts") or {}
    if (
        doc_lang in NO_LATIN_SPLIT_LANGS
        and report.get("unit") == "structured"
        and head_lang
        and head_lang not in NO_LATIN_SPLIT_LANGS
        and head_lang != doc_lang
    ):
        return Check(
            id="heading_language",
            severity="fail",
            passed=False,
            message=(
                f"document language {doc_lang} was split with Latin headings ({head_lang}); "
                "use script-specific article markers or collector article rows"
            ),
            evidence={"document_language": doc_lang, "heading_counts": counts, "unit": report.get("unit")},
        )
    if doc_lang and head_lang and doc_lang != head_lang and sum(counts.values()) >= 8:
        return Check(
            id="heading_language",
            severity="warn",
            passed=True,
            message=(
                f"heading lexicon majority is {head_lang} but documents are {doc_lang}; "
                "review samples before trusting structure"
            ),
            evidence={
                "document_language": doc_lang,
                "heading_language": head_lang,
                "heading_counts": counts,
            },
        )
    return Check(
        id="heading_language",
        severity="warn",
        passed=True,
        message=(
            f"heading lexicon {head_lang or 'none'} vs document language {doc_lang or 'unknown'}"
        ),
        evidence={
            "document_language": doc_lang,
            "heading_language": head_lang,
            "heading_counts": counts,
        },
    )


def check_reconstruction_grounded(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    """Parent reconstructed body must equal glue of child title/number/body."""
    from .reconstruct import expected_glue_from_children

    if corpus is None or corpus.empty:
        return Check(
            id="reconstruction_grounded",
            severity="fail",
            passed=True,
            message="no corpus",
            evidence={},
        )
    if "reconstructed_from_articles" not in corpus.columns:
        return Check(
            id="reconstruction_grounded",
            severity="warn",
            passed=True,
            message="no reconstruction columns",
            evidence={},
        )
    mismatches = 0
    checked = 0
    samples: list[str] = []
    laws = corpus[corpus["record_type"] == "law"] if "record_type" in corpus.columns else corpus
    for rec in laws.itertuples(index=False):
        if not bool(getattr(rec, "reconstructed_from_articles", False)):
            continue
        if str(getattr(rec, "reconstruction_gap_note", "") or "") in {
            "rss_abort_slug",
            "reconstruct_budget",
        }:
            continue
        checked += 1
        iid = str(getattr(rec, "instrument_id", "") or "")
        kids = corpus[
            (corpus["instrument_id"] == iid) & (corpus["record_type"].isin(["article", "section"]))
        ]
        children = [
            {
                "id": str(getattr(k, "source_id", "") or ""),
                "title": str(getattr(k, "article_title", "") or getattr(k, "title", "") or ""),
                "article_number": str(getattr(k, "article_number", "") or ""),
                "body": str(getattr(k, "body", "") or ""),
            }
            for k in kids.itertuples(index=False)
        ]
        expected = expected_glue_from_children(children)
        body = str(getattr(rec, "body", "") or "")
        if bool(getattr(rec, "reconstruction_truncated", False)):
            if not expected.startswith(body) and body != expected[: len(body)]:
                mismatches += 1
                if len(samples) < 5:
                    samples.append(iid)
            continue
        if body != expected:
            mismatches += 1
            if len(samples) < 5:
                samples.append(iid)
    ok = mismatches == 0
    return Check(
        id="reconstruction_grounded",
        severity="fail",
        passed=ok,
        message="reconstructed parents match child glue" if ok else f"{mismatches} reconstructed parents fail glue",
        evidence={"checked": checked, "mismatches": mismatches, "samples": samples},
    )


def check_empty_parents_reconstructed(report: dict[str, Any]) -> Check:
    n = int(report.get("n_empty_parents_with_articles_not_reconstructed") or 0)
    return Check(
        id="empty_parents_with_articles",
        severity="fail",
        passed=n == 0,
        message="eligible empty parents all have law rows" if n == 0 else f"{n} empty parents with articles were dropped",
        evidence={"n_empty_parents_with_articles_not_reconstructed": n},
    )


def check_parent_laws(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    """Fail if source had instruments but GraphRAG corpus has no law rows."""
    n_in = int(report.get("n_laws_in") or 0)
    n_law_rows = 0
    if corpus is not None and not corpus.empty and "record_type" in corpus.columns:
        n_law_rows = int((corpus["record_type"] == "law").sum())
    n_law_rows = int(report.get("n_law_rows") or n_law_rows)
    if n_in > 0 and n_law_rows == 0:
        return Check(
            id="parent_laws",
            severity="fail",
            passed=False,
            message=(
                f"source has {n_in} laws but corpus has 0 law rows "
                "(articles were indexed without parent instruments)"
            ),
            evidence={"n_laws_in": n_in, "n_law_rows": n_law_rows},
        )
    return Check(
        id="parent_laws",
        severity="warn",
        passed=True,
        message=f"parent instruments present ({n_law_rows} law rows from {n_in} source laws)",
        evidence={"n_laws_in": n_in, "n_law_rows": n_law_rows},
    )


def check_structure(corpus: pd.DataFrame, report: dict[str, Any]) -> Check:
    unit = str(report.get("unit") or "")
    n = int(len(corpus)) if corpus is not None else 0
    structured_rows = 0
    if corpus is not None and not corpus.empty:
        if "hierarchy_path" in corpus.columns:
            structured_rows = int((corpus["hierarchy_path"].fillna("").astype(str).str.len() > 0).sum())
        if "record_type" in corpus.columns:
            structured_rows = max(
                structured_rows,
                int(corpus["record_type"].isin(["article", "section"]).sum()),
            )
    coverage = structured_rows / float(n) if n else 0.0
    # Article or structured units are success. Pure law-level is a warning, not a fail:
    # many gazettes have no title/section markers.
    if unit in {"article", "structured", "law+article", "law+structured"} or coverage >= 0.5:
        return Check(
            id="legal_structure",
            severity="warn",
            passed=True,
            message=f"retrieval units are structured ({unit}, coverage={coverage:.2f})",
            evidence={"unit": unit, "structured_rows": structured_rows, "coverage": coverage},
        )
    return Check(
        id="legal_structure",
        severity="warn",
        passed=True,
        message=(
            "kept whole-instrument units; no title/article/section headings detected "
            "(expected for some gazettes)"
        ),
        evidence={"unit": unit, "structured_rows": structured_rows, "coverage": coverage},
    )


def verify_normalized_corpus(
    corpus: pd.DataFrame,
    report: dict[str, Any],
    *,
    slug: str = "",
) -> dict[str, Any]:
    """Run all normalization verifiers. Fail-closed on any failed `fail` check."""
    checks = [
        check_nonempty(corpus, report),
        check_entry_cids(corpus, report),
        check_no_invented_text(report),
        check_html_residual(corpus),
        check_short_bodies(corpus),
        check_parent_laws(corpus, report),
        check_reconstruction_grounded(corpus, report),
        check_empty_parents_reconstructed(report),
        check_structure(corpus, report),
        check_heading_language(corpus, report),
    ]
    failed = [c for c in checks if c.severity == "fail" and not c.passed]
    admitted = not failed
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "admitted": admitted,
        "n_checks": len(checks),
        "n_failed": len(failed),
        "failed_ids": [c.id for c in failed],
        "checks": [c.to_dict() for c in checks],
        "blocks_graphrag": not admitted,
    }


class NormalizationAdmissionError(RuntimeError):
    """Raised when verifiers refuse to send a corpus to GraphRAG."""


def verify_source(source: str) -> dict[str, Any]:
    """Load a Hub/local pack, normalize, and run verifiers (no GraphRAG)."""
    from .build import CACHE
    from .catalog import get_country
    from .normalize import build_corpus, load_source

    country = get_country(source)
    local = country.get("local_source_dir")
    laws, articles, source_meta = load_source(local or country["repo"], CACHE)
    corpus, report = build_corpus(laws, articles, source_meta)
    verdict = verify_normalized_corpus(corpus, report, slug=country["slug"])
    report["verification"] = verdict
    return {
        "slug": country["slug"],
        "source": country["repo"],
        "n_out": report.get("n_out"),
        "unit": report.get("unit"),
        "verification": verdict,
        "drops": report.get("drops"),
    }
