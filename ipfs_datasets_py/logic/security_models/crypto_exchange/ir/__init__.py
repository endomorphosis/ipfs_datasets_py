"""Canonical security IR helpers for crypto exchange verification."""

from .canonicalize import (
    canonicalize_domain_coverage_report,
    canonicalize_domain_coverage_report_json,
    canonicalize_ir,
    canonicalize_ir_json,
)
from .cid import calculate_model_cid
from .examples import example_minimal_exchange_model, example_xaman_wallet_security_model
from .schema import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
    KNOWN_SECURITY_DOMAINS,
    PRODUCTION_SECURITY_DOMAINS,
    XAMAN_SECURITY_DOMAINS,
    SecurityModelIR,
    check_domain_coverage,
    claim_domains,
    domain_coverage_report,
    validate_domain_coverage,
    validate_ir,
)

__all__ = [
    'DEFAULT_THREAT_MODEL_ASSUMPTIONS',
    'KNOWN_SECURITY_DOMAINS',
    'PRODUCTION_SECURITY_DOMAINS',
    'XAMAN_SECURITY_DOMAINS',
    'SecurityModelIR',
    'calculate_model_cid',
    'canonicalize_domain_coverage_report',
    'canonicalize_domain_coverage_report_json',
    'canonicalize_ir',
    'canonicalize_ir_json',
    'check_domain_coverage',
    'claim_domains',
    'domain_coverage_report',
    'example_minimal_exchange_model',
    'example_xaman_wallet_security_model',
    'validate_domain_coverage',
    'validate_ir',
]
