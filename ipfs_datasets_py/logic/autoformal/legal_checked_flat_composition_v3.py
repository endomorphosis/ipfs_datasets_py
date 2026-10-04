"""Versioned source dependency check before existing flat-rule composition.

This version supports explicit editorial captions; frozen v1/v2 remain unchanged.

The dependency checker receives source text and the committed plan only. It
cannot inspect predicted rules, training labels, or reference answers. Passing
this declared structural profile does not establish legal independence or
source meaning. Existing decoders and their historical evaluations are unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import legal_flat_scope_dependencies_v3 as dependencies
from . import legal_rule_list_composition as composition

SCHEMA = 'legal-checked-flat-composition/v3'
FALSE = {'qualified': False, 'admitted': False, 'proof_authority': False,
         'source_semantics_verified': False, 'independent_scope_verified': False,
         'training_executed': False, 'model_inference_executed': False}


def producer_pins():
    return dependencies.producer_pins() | composition.producer_pins() | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_PINS = producer_pins()


def compose_checked_flat(source, source_plan, clause_predictions, *, expected_plan_sha256):
    """Return the unchanged composition or an explicit structural deferral.

    The expected plan commitment must come from an authenticated upstream
    receipt. Hashing an arbitrary supplied plan does not authenticate its origin.
    Vetoed predictions are hashed for evidence but are never composed or emitted.
    """
    composition._require(producer_pins() == _PINS, 'checked composition producer drift')
    composition._require(type(clause_predictions) is list and len(clause_predictions) <= 8,
                         'bounded complete prediction list required')
    predictions_sha = composition.digest(clause_predictions)
    evidence = dependencies.prepare_flat_scope_dependencies(
        source, source_plan, expected_plan_sha256=expected_plan_sha256)
    dependencies.validate_flat_scope_dependencies(
        source, source_plan, evidence, expected_plan_sha256=expected_plan_sha256)
    allowed = evidence['allows_flat_composition']
    composition._require(type(allowed) is bool, 'Boolean dependency decision required')
    value = composition.compose_rule_list(source_plan, clause_predictions,
        expected_plan_sha256=expected_plan_sha256) if allowed else None
    report = {'schema': SCHEMA, 'source_sha256': source['source_sha256'],
        'source_plan_sha256': expected_plan_sha256, 'clause_predictions_sha256': predictions_sha,
        'dependency_evidence': evidence, 'status': 'composed' if allowed else 'deferred',
        'reason': None if allowed else 'source_dependency_outside_declared_flat_profile',
        'composition': value, 'canonical_ir': None if value is None else value['canonical_ir'],
        'source_only_dependency_check': True, 'producer_pins': _PINS, **FALSE}
    report['report_sha256'] = composition.digest(report)
    return report


def validate_checked_flat(report, source, source_plan, clause_predictions, *, expected_plan_sha256):
    """Recreate all source, dependency, rule, occurrence and authority fields."""
    expected = compose_checked_flat(source, source_plan, clause_predictions,
        expected_plan_sha256=expected_plan_sha256)
    composition._require(composition._wire(report) == composition._wire(expected),
                         'checked composition differs from authoritative regeneration')
    return True


__all__ = ['compose_checked_flat', 'validate_checked_flat', 'producer_pins', 'SCHEMA']
