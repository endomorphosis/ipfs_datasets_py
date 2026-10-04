from __future__ import annotations

from dataclasses import MISSING, fields
import hashlib
from typing import Dict, Type

from municipal_scrape_workspace.hybrid_legal_ir import (
    ActionFrame,
    Atom,
    BaseFrame,
    CanonicalId,
    Condition,
    Entity,
    EventFrame,
    LegalIR,
    Norm,
    Query,
    Rule,
    StateFrame,
    TemporalConstraint,
    TemporalExpr,
)

CORE_IR_DATACLASSES: tuple[Type[object], ...] = (
    CanonicalId,
    Entity,
    TemporalExpr,
    TemporalConstraint,
    BaseFrame,
    ActionFrame,
    EventFrame,
    StateFrame,
    Atom,
    Condition,
    Norm,
    Rule,
    Query,
    LegalIR,
)

EXPECTED_SCHEMA_CHECKSUMS: Dict[str, str] = {
    "CanonicalId": "bf897abdac822e5b6671b1903165b80514cec7874ecb0b6b2e514aae77010146",
    "Entity": "72edc5a0fa2ccac4a3a2435184b9e64f70bb306137ce53cb3dda612499e53908",
    "TemporalExpr": "ac3aa943719e890efcc8acc2426008327f741e97b3f53ff711065b341f4c4644",
    "TemporalConstraint": "5322ced905ae2ee5b0a06a0c2c116a09070275b0422c0e9f013d2e87dba52eef",
    "BaseFrame": "fc48525a11043cddc88a7de2f6331ccfba01fc2a904ba4de4e230909248b7fc0",
    "ActionFrame": "78fd4a668041ba8ae1b5b27803c789e75c81cb520c45dc3bd028e5cd18381283",
    "EventFrame": "27b9a856e9f113fde8075c22c0c1482d0ee9e0d0ca2577a0e055a12fa13a6250",
    "StateFrame": "e415aaf05d307d84bd48af54915b316c48442a0d15765655f679984ccfd0dcfe",
    "Atom": "121f5cddc129f4ed77f26a34ef7aed1dd044bff140e0661b2978459c98afde2a",
    "Condition": "6166b1500dde538a20805be842f88af6169811fc5389d9db480706848043e5a6",
    "Norm": "c112a902c31bc4664e91e43f828568d90495c3642705cbe08aaa07836ab47db0",
    "Rule": "8fe8f3e7bd123fc4b5bd397e9f4f69f01c1638beea4dc7bf07f0cc94faba5024",
    "Query": "2123c435d909482116ae421bc8d88463dac234eb4264f4ac96c66cd96af3f50b",
    "LegalIR": "4d381ae027cce90f8377039ba409df628743cea245505c80692647be43d5f646",
}

EXPECTED_COMBINED_CHECKSUM = "d4d4ab2b8cb57d832f51c1fa199f7832e40219008be09a71b592b3caf4549635"


def _annotation_text(cls: Type[object], field_name: str) -> str:
    for base in cls.__mro__:
        annotations = getattr(base, "__annotations__", None) or {}
        if field_name in annotations:
            return str(annotations[field_name])
    return "Any"


def _schema_signature_checksum(cls: Type[object]) -> str:
    lines = []
    for fld in fields(cls):
        default_kind = "required"
        if fld.default is not MISSING:
            default_kind = "default"
        elif fld.default_factory is not MISSING:  # type: ignore[attr-defined]
            default_kind = "default_factory"
        lines.append(
            "|".join(
                [
                    fld.name,
                    _annotation_text(cls, fld.name),
                    default_kind,
                    "kw_only" if getattr(fld, "kw_only", False) else "positional",
                ]
            )
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _all_schema_checksums() -> Dict[str, str]:
    return {cls.__name__: _schema_signature_checksum(cls) for cls in CORE_IR_DATACLASSES}


def test_core_ir_dataclass_schema_snapshot_checksums() -> None:
    """Guard against accidental schema drift across core LegalIR dataclasses."""
    assert _all_schema_checksums() == EXPECTED_SCHEMA_CHECKSUMS


def test_core_ir_dataclass_combined_schema_checksum() -> None:
    checksums = _all_schema_checksums()
    payload = "\n".join(f"{name}:{checksums[name]}" for name in EXPECTED_SCHEMA_CHECKSUMS)
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == EXPECTED_COMBINED_CHECKSUM
