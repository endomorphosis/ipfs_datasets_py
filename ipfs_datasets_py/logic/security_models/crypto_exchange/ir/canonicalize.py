"""Deterministic canonicalization for security IR artifacts."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .schema import SecurityModelIR, domain_coverage_report, json_ready, validate_domain_coverage, validate_ir


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def canonicalize_ir_json(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Serialize a security model with stable key ordering."""

    normalized = validate_ir(model)
    payload = _normalize(json_ready(normalized))
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def canonicalize_ir(model: SecurityModelIR | Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 bytes for a security model."""

    return canonicalize_ir_json(model).encode('utf-8')


def canonicalize_domain_coverage_report_json(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_domains: Iterable[str] | None = None,
    fail_closed: bool = False,
) -> str:
    """Serialize a deterministic, CID-addressable domain coverage report for *model*.

    When ``fail_closed`` is ``True`` this raises :class:`ValueError` (via
    :func:`ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema.validate_domain_coverage`)
    if any required production or Xaman security domain lacks claim
    coverage, instead of silently emitting a report with ``fully_covered: false``.
    """

    if fail_closed:
        validate_domain_coverage(model, required_domains=required_domains)
    report = domain_coverage_report(model, required_domains=required_domains)
    payload = _normalize(json_ready(report))
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def canonicalize_domain_coverage_report(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    required_domains: Iterable[str] | None = None,
    fail_closed: bool = False,
) -> bytes:
    """Return canonical UTF-8 bytes for a domain coverage report of *model*."""

    return canonicalize_domain_coverage_report_json(
        model,
        required_domains=required_domains,
        fail_closed=fail_closed,
    ).encode('utf-8')
