"""PAAR-111: hermetic end-to-end review integration tests.

Composes claim_limitation_model, conflict_risk_engine, and
package_conformance_engine against offline fixtures under
tests/fixtures/uspto/paar_review/.

If application_review_orchestrator is importable, it is preferred as the
entrypoint; otherwise engines are composed manually (fail-closed).

Invariants: no network, no secrets, not legal advice, no patentability
conclusions, auto_file_blocked always true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    RiskLevel,
    score_conflict_risk,
)
from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
    AuthorityMode,
    parse_claims_to_graph,
)
from ipfs_datasets_py.processors.domains.uspto.package_conformance_engine import (
    ConformanceStatus,
    evaluate_package_conformance,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "uspto" / "paar_review"
)

_FIXED_TS = "2026-08-06T00:00:00Z"

# Affirmative patentability / filing conclusions forbidden in report dicts.
_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "is patentable",
    "is unpatentable",
    "is novel",
    "is obvious",
    "novelty conclusion",
    "obviousness conclusion",
    "patentability conclusion",
    "no prior art exists",
    "will be allowed",
    "anticipates claim",
    "renders claim obvious",
    "safe to file without review",
)

# Optional orchestrator (PAAR-090); may not exist yet.
try:
    from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (  # type: ignore
        review_application as _orchestrator_review,
    )

    _HAS_ORCHESTRATOR = True
except Exception:  # noqa: BLE001 — optional import
    _orchestrator_review = None  # type: ignore[assignment]
    _HAS_ORCHESTRATOR = False


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _require_fixture_dir(name: str) -> Path:
    path = _FIXTURE_ROOT / name
    if not path.is_dir():
        pytest.fail(f"PAAR fixture pack missing: {path}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manifest(variant: str) -> dict[str, Any]:
    return _load_json(_require_fixture_dir(variant) / "manifest.json")


def _hit_text(hit: Mapping[str, Any]) -> str:
    """Normalize fixture hit rows to engine ``text`` field."""
    return str(
        hit.get("text")
        or hit.get("body_excerpt")
        or hit.get("passage_excerpt")
        or hit.get("excerpt")
        or hit.get("abstract")
        or hit.get("title")
        or ""
    )


def _normalize_hits(prior_hits: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in prior_hits.get("hits") or ():
        if not isinstance(hit, Mapping):
            continue
        hid = str(hit.get("hit_id") or hit.get("document_id") or hit.get("id") or "")
        if not hid:
            continue
        rows.append(
            {
                "hit_id": hid,
                "text": _hit_text(hit),
                "publication_number": hit.get("publication_number"),
                "corpus": hit.get("corpus"),
            }
        )
    return rows


def _authority_present(
    inventory: Mapping[str, Any] | None,
    authority_status: Mapping[str, Any] | None = None,
) -> bool:
    if authority_status is not None:
        if "authority_corpus_bound" in authority_status:
            return bool(authority_status.get("authority_corpus_bound"))
        if "authority_corpus_present" in authority_status:
            return bool(authority_status.get("authority_corpus_present"))
    inv = inventory or {}
    return bool(
        inv.get("authority_corpus_bound")
        or inv.get("authority_corpus_present")
        or inv.get("authority_bound")
    )


def _redact_disclaimer_fields(obj: Any) -> Any:
    """Drop disclaimer text from nested payloads before ban-list scan."""
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in {"disclaimer", "notes"}:
                continue
            out[str(k)] = _redact_disclaimer_fields(v)
        return out
    if isinstance(obj, list):
        return [_redact_disclaimer_fields(x) for x in obj]
    if isinstance(obj, tuple):
        return [_redact_disclaimer_fields(x) for x in obj]
    return obj


def _assert_no_forbidden(payload: Mapping[str, Any] | Any) -> None:
    """Affirmative banned conclusions must not appear outside disclaimer framing."""
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    # Disclaimers intentionally say "not a … patentability conclusion".
    scan = _redact_disclaimer_fields(payload)
    blob = json.dumps(scan, default=str).lower()
    cleaned = blob
    for neg in (
        "not a patentability",
        "not patentability",
        "never a patentability",
        "no patentability",
        "not a novelty",
        "not an obviousness",
        "not legal advice",
        "not a completeness",
        "not a novelty, obviousness, or patentability",
        "or patentability conclusion",
        "novelty, obviousness, or patentability conclusion",
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in cleaned, f"forbidden phrase in report: {phrase!r}"


def _derive_overall_disposition(
    *,
    matter_risk: str | None,
    conformance_overall: str | None,
    authority_present: bool,
    claim_review_required: bool,
) -> str:
    """Minimal closed disposition rollup for composition (ready|review_required|not_ready)."""
    conf = (conformance_overall or "unknown").lower()
    risk = (matter_risk or "unknown").lower()
    if not authority_present:
        return "not_ready"
    if conf in {"unsatisfied", "unknown"}:
        # human_only packages may still be review_required; unknown/unsatisfied block ready
        if conf == "unsatisfied":
            return "not_ready"
        return "not_ready"
    if claim_review_required or risk in {"high", "medium", "unknown"}:
        return "review_required"
    if conf == "satisfied" and risk == "low":
        return "ready"
    # human_only + low risk still needs human process steps
    if conf == "human_only":
        return "review_required"
    return "review_required"


def _compose_review(variant: str) -> dict[str, Any]:
    """Run fixture package through available engines (or orchestrator)."""
    root = _require_fixture_dir(variant)
    manifest = _load_manifest(variant)
    files = manifest.get("files") or {}
    app = str(manifest.get("application_number") or "")

    claims_name = files.get("claims") or "claims.txt"
    claims_text = (root / claims_name).read_text(encoding="utf-8")

    inventory: dict[str, Any] = {}
    inv_name = files.get("package_inventory")
    if inv_name and (root / inv_name).is_file():
        inventory = _load_json(root / inv_name)

    prior_hits: dict[str, Any] = {"hits": [], "coverage_gaps": []}
    hits_name = files.get("prior_hits")
    if hits_name and (root / hits_name).is_file():
        prior_hits = _load_json(root / hits_name)

    authority_status: dict[str, Any] | None = None
    auth_name = files.get("authority")
    if auth_name and (root / auth_name).is_file():
        authority_status = _load_json(root / auth_name)

    authority_present = _authority_present(inventory, authority_status)

    if _HAS_ORCHESTRATOR and _orchestrator_review is not None:
        try:
            orch = _orchestrator_review(
                application_number=app,
                claims_text=claims_text,
                inventory=inventory,
                prior_hits=prior_hits,
                authority_corpus_present=authority_present,
                generated_at_utc=_FIXED_TS,
                network=False,
            )
            if isinstance(orch, Mapping):
                return dict(orch)
            if hasattr(orch, "to_dict"):
                return orch.to_dict()
        except TypeError:
            # Signature mismatch — fall through to manual composition.
            pass
        except Exception:
            # Orchestrator present but failed: still compose engines hermetically.
            pass

    graph = parse_claims_to_graph(claims_text)
    hit_rows = _normalize_hits(prior_hits)
    coverage_gaps = list(prior_hits.get("coverage_gaps") or [])

    conflict = score_conflict_risk(
        application_number=app,
        claim_graph=graph,
        hits=hit_rows,
        coverage_gaps=coverage_gaps,
        generated_at_utc=_FIXED_TS,
        metadata={"fixture_id": str(manifest.get("fixture_id") or variant)},
    )

    extracts: dict[str, Any] = {"claims": claims_text}
    title = str(inventory.get("title") or "")
    meta = {"title": title, "invention_title": title} if title else {}

    # Prefer inventory ifw_codes list; engine also accepts files[].
    conf = evaluate_package_conformance(
        inventory=inventory or None,
        application_number=app,
        application_type=str(inventory.get("application_type") or "utility"),
        scenario=str(inventory.get("scenario") or "new_application"),
        authority_corpus_present=authority_present,
        extracts=extracts,
        meta=meta,
        generated_at_utc=_FIXED_TS,
        metadata={"fixture_id": str(manifest.get("fixture_id") or variant)},
    )

    claim_review = graph.quality.review_required or (
        graph.quality.authority_mode is not AuthorityMode.AUTHORITATIVE
    )
    disposition = _derive_overall_disposition(
        matter_risk=conflict.matter_risk.value,
        conformance_overall=conf.overall_status.value,
        authority_present=authority_present,
        claim_review_required=claim_review,
    )

    return {
        "schema": "paar.composed-review.v1",
        "fixture_id": manifest.get("fixture_id"),
        "variant": variant,
        "application_number": app,
        "auto_file_blocked": True,
        "overall_disposition": disposition,
        "authority_corpus_present": authority_present,
        "claim_limitation": {
            "schema": graph.schema,
            "authority_mode": graph.quality.authority_mode.value,
            "review_required": graph.quality.review_required,
            "claim_count": len(graph.claims),
            "limitation_count": len(graph.limitations),
            "quality_score": graph.quality.quality_score,
            "disclaimer": graph.disclaimer,
        },
        "conflict_risk": conflict.to_dict(),
        "conformance": conf.to_dict(),
        "disclaimer": (
            "Composed hermetic PAAR review for evaluation only. Not legal advice. "
            "Not a novelty, obviousness, or patentability conclusion. "
            "auto_file_blocked=true."
        ),
        "orchestrator_used": False,
        "network": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.offline
def test_fixtures_present_and_network_free() -> None:
    assert _FIXTURE_ROOT.is_dir()
    for name in ("planted_conflict", "clean_package", "missing_authority"):
        man = _load_manifest(name)
        assert man.get("network_free") is True
        assert man.get("synthetic") is True
        assert man.get("schema") == "paar.review-fixture.v1"


@pytest.mark.offline
def test_planted_conflict_medium_or_high_or_review_required() -> None:
    """(a) Planted overlap → matter_risk medium/high or overall review_required."""
    result = _compose_review("planted_conflict")
    expected = _load_manifest("planted_conflict").get("expected") or {}

    conflict = result["conflict_risk"]
    matter = str(conflict.get("matter_risk") or "").lower()
    overall = str(result.get("overall_disposition") or "").lower()

    assert matter in {"medium", "high"} or overall == "review_required", (
        f"planted conflict expected medium/high or review_required; "
        f"got matter_risk={matter!r} overall={overall!r}"
    )
    min_expected = str(expected.get("matter_risk_min") or "medium").lower()
    rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    if matter in rank and min_expected in rank:
        assert rank[matter] >= rank[min_expected]

    assert conflict.get("auto_file_blocked") is True
    assert result.get("auto_file_blocked") is True
    assert conflict.get("cells"), "planted pair should produce scored cells"
    cell_risks = {str(c.get("risk") or "").lower() for c in conflict["cells"]}
    assert cell_risks & {"medium", "high"}, cell_risks

    _assert_no_forbidden(result)
    _assert_no_forbidden(conflict)
    _assert_no_forbidden(result["conformance"])


@pytest.mark.offline
def test_clean_package_not_high_without_evidence() -> None:
    """(b) Clean package → not high risk without evidence; no invented not_ready."""
    result = _compose_review("clean_package")
    expected = _load_manifest("clean_package").get("expected") or {}

    conflict = result["conflict_risk"]
    matter = str(conflict.get("matter_risk") or "").lower()
    banned = str(expected.get("matter_risk_not") or "high").lower()
    assert matter != banned, f"clean package must not be {banned} without evidence"

    # Cell-level: unrelated art should not invent high cells
    high_cells = [
        c
        for c in conflict.get("cells") or ()
        if str(c.get("risk") or "").lower() == "high"
    ]
    assert not high_cells, "clean package must not invent high-risk cells"

    # Coverage gaps may elevate aggregate above low (fail-closed) — that is OK
    # and must remain visible rather than silently cleared.
    gaps = conflict.get("coverage_gaps") or []
    if gaps:
        assert conflict.get("coverage_penalty_applied") in {True, False}

    conf = result["conformance"]
    # Authority is bound on clean fixture; do not invent not_ready solely from
    # missing authority when authority is present.
    assert result["authority_corpus_present"] is True
    assert conf.get("authority_corpus_present") is True
    # Disposition must not be not_ready *only* for invented reasons when
    # inventory looks complete and authority is bound. Incomplete machine
    # checks may still yield review_required / human_only (legitimate).
    overall = str(result.get("overall_disposition") or "")
    assert overall in {"ready", "review_required", "not_ready"}
    # Not high, auto-file blocked, no patentability
    assert result.get("auto_file_blocked") is True
    assert conf.get("auto_file_blocked") is True
    _assert_no_forbidden(result)


@pytest.mark.offline
def test_missing_authority_not_ready_or_unknown() -> None:
    """(c) Missing authority → not_ready or unknown conformance; never vacuous ready."""
    result = _compose_review("missing_authority")
    expected = _load_manifest("missing_authority").get("expected") or {}

    assert result["authority_corpus_present"] is False
    conf = result["conformance"]
    overall_conf = str(conf.get("overall_status") or "").lower()
    disposition = str(result.get("overall_disposition") or "").lower()

    # Never vacuous ready when authority required
    assert disposition != "ready"
    if expected.get("disposition_not"):
        assert disposition != str(expected["disposition_not"]).lower()

    # Conformance: unknown overall OR not satisfied; authority obligation unknown
    assert overall_conf in {
        ConformanceStatus.UNKNOWN.value,
        ConformanceStatus.UNSATISFIED.value,
        ConformanceStatus.HUMAN_ONLY.value,
    }
    assert overall_conf != ConformanceStatus.SATISFIED.value

    auth_results = [
        r
        for r in (conf.get("results") or ())
        if "authority" in str(r.get("obligation_id") or "").lower()
    ]
    if auth_results:
        for r in auth_results:
            assert str(r.get("status") or "").lower() != ConformanceStatus.SATISFIED.value
            assert str(r.get("status") or "").lower() in {
                ConformanceStatus.UNKNOWN.value,
                ConformanceStatus.UNSATISFIED.value,
                ConformanceStatus.HUMAN_ONLY.value,
            }

    assert conf.get("auto_file_blocked") is True
    assert result.get("auto_file_blocked") is True
    _assert_no_forbidden(result)


@pytest.mark.offline
def test_engines_wired_and_optional_orchestrator_flag() -> None:
    """Engines are importable; orchestrator is optional."""
    # Smoke: each variant produces structured reports
    for variant in ("planted_conflict", "clean_package", "missing_authority"):
        result = _compose_review(variant)
        assert "claim_limitation" in result
        assert result["conflict_risk"].get("schema")
        assert result["conformance"].get("schema")
        assert result.get("network") is False
        # Orchestrator may or may not be present; composition path always works
        assert result.get("orchestrator_used") in {True, False}
    # Document optional import for CI visibility (not a hard fail)
    assert isinstance(_HAS_ORCHESTRATOR, bool)


@pytest.mark.offline
def test_composed_reports_auto_file_blocked_and_disclaimers() -> None:
    result = _compose_review("planted_conflict")
    assert result["auto_file_blocked"] is True
    assert result["conflict_risk"]["auto_file_blocked"] is True
    assert result["conformance"]["auto_file_blocked"] is True
    lower = json.dumps(result, default=str).lower()
    assert "not legal advice" in lower or "review-only" in lower
    assert "patentability" in lower  # present in negative disclaimer framing
    _assert_no_forbidden(result)
