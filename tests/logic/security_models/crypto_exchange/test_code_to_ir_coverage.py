"""Fail-closed code-to-IR domain coverage checks (PORTAL-CXTP-062).

These tests keep three things in sync:

1. ``ir.schema.PRODUCTION_SECURITY_DOMAINS`` / ``XAMAN_SECURITY_DOMAINS`` --
   the typed IR's domain vocabulary.
2. The executable domain vocabulary elsewhere in the codebase
   (``prove_all.CLAIM_DOMAINS`` for production claims,
   ``XamanSourceExtractor._security_category`` for the Xaman corpus).
3. ``docs/security_verification/code_to_ir_evidence_matrix.md`` -- the
   human-reviewable evidence matrix that documents extractor -> claim ->
   IR-field -> evidence-kind coverage for every domain.

If any of these three drift apart, or if a domain loses its claim
coverage, these tests fail closed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_source_extractor import (
    XamanSourceExtractor,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import (
    example_minimal_exchange_model,
    example_xaman_wallet_security_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    KNOWN_SECURITY_DOMAINS,
    PRODUCTION_SECURITY_DOMAINS,
    XAMAN_SECURITY_DOMAINS,
    SecurityModelIR,
    check_domain_coverage,
    validate_domain_coverage,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import CLAIM_DOMAINS


REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_MATRIX_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'code_to_ir_evidence_matrix.md'

# Representative corpus-relative paths for every category recognized by
# ``XamanSourceExtractor._security_category``. Kept here (rather than only
# inside the extractor) so a drift between the extractor's classifier and
# the schema's ``XAMAN_SECURITY_DOMAINS`` vocabulary is caught explicitly.
_XAMAN_CATEGORY_PROBE_PATHS = {
    'vault': 'src/common/libs/vault.ts',
    'payload': 'src/common/libs/payload/create.ts',
    'ledger': 'src/common/libs/ledger/transaction.ts',
    'auth_component': 'src/screens/Overlay/Authenticate/index.tsx',
    'service': 'src/services/NetworkService.ts',
    'store': 'src/store/reducers/account.ts',
    'e2e_flow': 'e2e/signing.feature',
}


# ---------------------------------------------------------------------------
# Domain vocabulary drift guards
# ---------------------------------------------------------------------------


def test_production_claim_domains_are_subset_of_known_production_domains():
    """``prove_all.CLAIM_DOMAINS`` values must all be modeled security domains."""

    claim_domain_values = set(CLAIM_DOMAINS.values())
    unknown = claim_domain_values - PRODUCTION_SECURITY_DOMAINS
    assert not unknown, (
        f'prove_all.CLAIM_DOMAINS references domain(s) missing from '
        f'ir.schema.PRODUCTION_SECURITY_DOMAINS: {sorted(unknown)}'
    )


def test_known_production_domains_are_all_exercised_by_a_claim():
    """Every declared production domain must have at least one real claim id."""

    claim_domain_values = set(CLAIM_DOMAINS.values())
    unmodeled = PRODUCTION_SECURITY_DOMAINS - claim_domain_values
    assert not unmodeled, (
        f'ir.schema.PRODUCTION_SECURITY_DOMAINS declares domain(s) with no '
        f'claim in prove_all.CLAIM_DOMAINS: {sorted(unmodeled)}'
    )


def test_xaman_extractor_categories_are_subset_of_known_xaman_domains():
    """``XamanSourceExtractor`` categories must all be modeled security domains."""

    observed_categories = {
        XamanSourceExtractor._security_category(path)
        for path in _XAMAN_CATEGORY_PROBE_PATHS.values()
    }
    observed_categories.discard(None)
    unknown = observed_categories - XAMAN_SECURITY_DOMAINS
    assert not unknown, (
        f'XamanSourceExtractor._security_category produced domain(s) missing '
        f'from ir.schema.XAMAN_SECURITY_DOMAINS: {sorted(unknown)}'
    )


def test_known_xaman_domains_are_all_reachable_from_the_extractor():
    """Every declared Xaman domain must be reachable via a real corpus path."""

    observed_categories = {
        XamanSourceExtractor._security_category(path)
        for path in _XAMAN_CATEGORY_PROBE_PATHS.values()
    }
    unreachable = XAMAN_SECURITY_DOMAINS - observed_categories
    assert not unreachable, (
        f'ir.schema.XAMAN_SECURITY_DOMAINS declares domain(s) unreachable from '
        f'XamanSourceExtractor._security_category: {sorted(unreachable)}'
    )


def test_xaman_probe_paths_are_classified_into_their_expected_domain():
    for expected_domain, path in _XAMAN_CATEGORY_PROBE_PATHS.items():
        assert XamanSourceExtractor._security_category(path) == expected_domain


# ---------------------------------------------------------------------------
# Fixture coverage: production and Xaman fixtures individually
# ---------------------------------------------------------------------------


def test_production_fixture_has_full_domain_coverage():
    model = example_minimal_exchange_model()
    missing = check_domain_coverage(model, required_domains=PRODUCTION_SECURITY_DOMAINS)
    assert missing == []
    validate_domain_coverage(model, required_domains=PRODUCTION_SECURITY_DOMAINS)


def test_xaman_fixture_has_full_domain_coverage():
    model = example_xaman_wallet_security_model()
    missing = check_domain_coverage(model, required_domains=XAMAN_SECURITY_DOMAINS)
    assert missing == []
    validate_domain_coverage(model, required_domains=XAMAN_SECURITY_DOMAINS)


def test_production_fixture_alone_is_missing_xaman_only_domains():
    """Sanity check that the coverage gate is not vacuously true.

    ``ledger`` is shared by both domain vocabularies, so the production
    fixture (which models a ``ledger`` claim) is expected to cover it; every
    Xaman-only domain must still be reported missing.
    """

    model = example_minimal_exchange_model()
    missing = check_domain_coverage(model, required_domains=XAMAN_SECURITY_DOMAINS)
    xaman_only_domains = XAMAN_SECURITY_DOMAINS - PRODUCTION_SECURITY_DOMAINS
    assert set(missing) == xaman_only_domains


def test_xaman_fixture_alone_is_missing_most_production_domains():
    """Sanity check that the coverage gate is not vacuously true."""

    model = example_xaman_wallet_security_model()
    missing = check_domain_coverage(model, required_domains=PRODUCTION_SECURITY_DOMAINS)
    # The Xaman fixture models an application-level "ledger" claim, but not
    # withdrawals/deposits/hsm/capabilities/audit -- those remain production-only.
    assert missing, 'Xaman fixture unexpectedly covers every production domain'
    assert set(missing) <= PRODUCTION_SECURITY_DOMAINS


# ---------------------------------------------------------------------------
# Fixture coverage: combined production + Xaman claim coverage
# ---------------------------------------------------------------------------


def _combined_model() -> SecurityModelIR:
    """Merge the production and Xaman fixture claims into one model for a
    whole-of-corpus coverage check (production and Xaman claim ids are
    disjoint by construction, so this merge cannot mask a missing domain)."""

    production = example_minimal_exchange_model()
    xaman = example_xaman_wallet_security_model()
    combined = SecurityModelIR(
        schema_version=production.schema_version,
        model_id='combined-production-and-xaman-coverage',
        claims=list(production.claims) + list(xaman.claims),
    )
    return combined


def test_combined_fixtures_cover_every_known_security_domain():
    combined = _combined_model()
    missing = check_domain_coverage(combined, required_domains=KNOWN_SECURITY_DOMAINS)
    assert missing == [], f'Missing claim coverage for domain(s): {missing}'
    validate_domain_coverage(combined, required_domains=KNOWN_SECURITY_DOMAINS)


def test_combined_fixture_claim_ids_do_not_collide():
    production = example_minimal_exchange_model()
    xaman = example_xaman_wallet_security_model()
    production_ids = {claim['id'] for claim in production.claims}
    xaman_ids = {claim['id'] for claim in xaman.claims}
    assert not (production_ids & xaman_ids)


def test_removing_any_single_domains_claims_breaks_the_fail_closed_gate():
    """Prove the gate is fail-closed: dropping coverage for any one domain
    must cause ``validate_domain_coverage`` to raise, not silently pass."""

    combined = _combined_model()
    for domain in sorted(KNOWN_SECURITY_DOMAINS):
        remaining_claims = [claim for claim in combined.claims if claim['domain'] != domain]
        stripped = SecurityModelIR(
            schema_version=combined.schema_version,
            model_id=combined.model_id,
            claims=remaining_claims,
        )
        with pytest.raises(ValueError, match=domain):
            validate_domain_coverage(stripped, required_domains=KNOWN_SECURITY_DOMAINS)


# ---------------------------------------------------------------------------
# Evidence-matrix <-> code sync
# ---------------------------------------------------------------------------


def test_evidence_matrix_document_exists():
    assert EVIDENCE_MATRIX_PATH.is_file(), f'Missing evidence matrix: {EVIDENCE_MATRIX_PATH}'


def _matrix_text() -> str:
    return EVIDENCE_MATRIX_PATH.read_text(encoding='utf-8')


def test_evidence_matrix_documents_every_known_security_domain():
    text = _matrix_text()
    missing_domains = [
        domain
        for domain in sorted(KNOWN_SECURITY_DOMAINS)
        if not re.search(rf'`{re.escape(domain)}`', text)
    ]
    assert missing_domains == [], (
        f'docs/security_verification/code_to_ir_evidence_matrix.md is missing row(s) for: {missing_domains}'
    )


def test_evidence_matrix_documents_every_production_claim_id():
    text = _matrix_text()
    missing_claims = [claim_id for claim_id in sorted(CLAIM_DOMAINS) if claim_id not in text]
    assert missing_claims == [], (
        f'docs/security_verification/code_to_ir_evidence_matrix.md is missing production claim id(s): {missing_claims}'
    )


def test_evidence_matrix_references_domain_coverage_gate_functions():
    text = _matrix_text()
    for symbol in ('check_domain_coverage', 'validate_domain_coverage', 'KNOWN_SECURITY_DOMAINS'):
        assert symbol in text, f'Evidence matrix must document {symbol!r}'


def test_evidence_matrix_references_validation_command():
    text = _matrix_text()
    assert 'test_ir_schema.py' in text
    assert 'test_code_to_ir_coverage.py' in text
