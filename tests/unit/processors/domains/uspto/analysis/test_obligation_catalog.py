"""Unit tests for PAAR obligation catalog (PAAR-050)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.analysis.obligation_catalog import (
    OBLIGATION_CATALOG_SCHEMA,
    SEED_CATALOG_ID,
    AuthorityCite,
    AuthorityTier,
    FailClosedBehavior,
    Obligation,
    ObligationCatalog,
    ObligationCatalogError,
    ObligationSeverity,
    Applicability,
    EvidencePredicate,
    EvidencePredicateKind,
    guidance_never_above_regulation,
    load_seed_catalog,
    resolve_seed_path,
)

# Components required in seed (PAAR-050 / PAAR-053 acceptance)
_REQUIRED_COMPONENTS = {
    "claims",
    "specification",
    "drawings",
    "ads",
    "oath",
    "fees",
    "ids",
    "abstract",
    "title",
    "prior_art_us",
    "prior_art_foreign",
    "prior_art_npl",
}


def test_seed_path_resolves() -> None:
    path = resolve_seed_path()
    assert path.is_file()
    assert path.name == "obligation_catalog_seed.json"


def test_load_seed_catalog() -> None:
    catalog = load_seed_catalog()
    assert catalog.schema == OBLIGATION_CATALOG_SCHEMA
    assert catalog.catalog_id == SEED_CATALOG_ID
    assert catalog.content_digest
    assert len(catalog.content_digest) == 64
    assert len(catalog.obligations) >= 25
    # Hardened seed (PAAR-053/054)
    assert str(catalog.version).startswith("1.")


def test_each_obligation_has_required_fields() -> None:
    catalog = load_seed_catalog()
    for obl in catalog.obligations:
        assert obl.obligation_id
        assert obl.authority_cites or obl.guidance_cites
        assert obl.applicability.application_types
        assert obl.applicability.scenarios
        assert obl.evidence_predicates
        assert isinstance(obl.severity, ObligationSeverity)
        assert isinstance(obl.fail_closed, FailClosedBehavior)
        # Content-addressed
        assert len(obl.content_digest) == 64


def test_seed_covers_core_components() -> None:
    catalog = load_seed_catalog()
    components = {o.component for o in catalog.obligations if o.component}
    missing = _REQUIRED_COMPONENTS - components
    assert not missing, f"seed missing components: {missing}"


def test_abstract_word_limit_and_title_present() -> None:
    catalog = load_seed_catalog()
    ids = {o.obligation_id for o in catalog.obligations}
    assert any("abstract" in i for i in ids)
    assert any("title" in i for i in ids)
    abstract = next(o for o in catalog.obligations if "abstract" in o.obligation_id)
    kinds = {p.kind for p in abstract.evidence_predicates}
    assert EvidencePredicateKind.WORD_COUNT_MAX in kinds


def test_mpep_is_guidance_tier_not_controlling() -> None:
    catalog = load_seed_catalog()
    assert guidance_never_above_regulation(catalog) is True
    mpep_seen = False
    for obl in catalog.obligations:
        for g in obl.guidance_cites:
            if "MPEP" in g.citation.upper():
                mpep_seen = True
                assert g.tier is AuthorityTier.GUIDANCE
                assert g.is_controlling is False
        for c in obl.authority_cites:
            if "MPEP" in c.citation.upper():
                assert c.tier is AuthorityTier.GUIDANCE
                assert c.is_controlling is False
    assert mpep_seen, "expected at least one MPEP guidance cite in seed"


def test_guidance_cannot_be_marked_controlling() -> None:
    cite = AuthorityCite(
        citation="MPEP 601",
        tier=AuthorityTier.GUIDANCE,
        is_controlling=True,  # should be forced false
    )
    assert cite.is_controlling is False


def test_unknown_authority_fails_closed() -> None:
    catalog = load_seed_catalog()
    assert catalog.unknown_authority_status("obl:does-not-exist") == "unknown"
    # Meta obligation uses unknown tier
    meta = catalog.get("obl:utility:new:authority-corpus-bound")
    assert meta is not None
    assert catalog.unknown_authority_status(meta.obligation_id) == "unknown"


def test_applicable_filter_new_application() -> None:
    catalog = load_seed_catalog()
    applicable = catalog.applicable(
        application_type="utility", scenario="new_application"
    )
    assert applicable
    ids = {o.obligation_id for o in applicable}
    assert any("claims" in i for i in ids)
    assert any("specification" in i or "spec" in i for i in ids)


def test_ids_scenario_includes_process_hygiene() -> None:
    catalog = load_seed_catalog()
    ids_obs = [
        o
        for o in catalog.obligations
        if o.component == "ids" or "ids" in o.obligation_id
    ]
    assert ids_obs
    for o in ids_obs:
        assert o.severity in {
            ObligationSeverity.HUMAN_ONLY,
            ObligationSeverity.MAJOR,
            ObligationSeverity.BLOCKING,
            ObligationSeverity.INFORMATIONAL,
            ObligationSeverity.MINOR,
        }
        # Process hygiene predicates block auto-file
        joined = json.dumps(o.to_dict()).lower()
        assert "auto_file" in joined or "human" in joined


def test_catalog_digest_stable() -> None:
    a = load_seed_catalog()
    b = load_seed_catalog()
    assert a.content_digest == b.content_digest
    assert a.compute_digest() == a.content_digest


def test_duplicate_id_rejected() -> None:
    catalog = load_seed_catalog()
    obl = catalog.obligations[0]
    with pytest.raises(ObligationCatalogError) as ei:
        ObligationCatalog(
            catalog_id="test.dup",
            version="0.0.1",
            obligations=(obl, obl),
        )
    assert ei.value.code == "duplicate_id"


def test_obligation_requires_cite() -> None:
    with pytest.raises(ObligationCatalogError):
        Obligation(
            obligation_id="obl:test:empty",
            title="Empty",
            description="No cites",
            authority_cites=(),
            applicability=Applicability(),
            evidence_predicates=(
                EvidencePredicate(
                    kind=EvidencePredicateKind.DOCUMENT_PRESENT,
                    target="x",
                ),
            ),
            severity=ObligationSeverity.MINOR,
            fail_closed=FailClosedBehavior.UNKNOWN,
            guidance_cites=(),
        )


def test_round_trip_dict() -> None:
    catalog = load_seed_catalog()
    restored = ObligationCatalog.from_dict(catalog.to_dict())
    assert restored.catalog_id == catalog.catalog_id
    assert len(restored.obligations) == len(catalog.obligations)
    assert restored.compute_digest() == catalog.compute_digest()


def test_exhaustive_prior_art_corpus_obligations_present() -> None:
    """PAAR-054: US/ODP, foreign/EPO OPS, and NPL corpus obligations exist."""
    catalog = load_seed_catalog()
    ids = {o.obligation_id for o in catalog.obligations}
    assert "obl:prior-art:us-odp-corpus-searched" in ids
    assert "obl:prior-art:foreign-epo-ops-corpus-searched" in ids
    assert "obl:prior-art:npl-corpus-searched" in ids
    for oid in (
        "obl:prior-art:us-odp-corpus-searched",
        "obl:prior-art:foreign-epo-ops-corpus-searched",
        "obl:prior-art:npl-corpus-searched",
    ):
        obl = catalog.get(oid)
        assert obl is not None
        kinds = {p.kind for p in obl.evidence_predicates}
        assert EvidencePredicateKind.CORPUS_SEARCHED in kinds
    # Safety: no patentability automation obligation remains human_only
    safety = catalog.get("obl:prior-art:no-patentability-conclusion")
    assert safety is not None
    assert safety.severity is ObligationSeverity.HUMAN_ONLY


def test_disclaimer_present() -> None:
    catalog = load_seed_catalog()
    lowered = catalog.disclaimer.lower()
    assert "not legal advice" in lowered
    assert "mpep" in lowered
    assert "guidance" in lowered
