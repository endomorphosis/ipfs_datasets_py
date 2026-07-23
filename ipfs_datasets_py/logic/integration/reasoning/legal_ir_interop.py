"""Standards and interchange interoperability for LegalIR artifacts.

The public compiler API is intentionally daemon-free and JSON-oriented.  This
module adds deterministic interchange envelopes for selected external profiles:
legal JSON, legal XML, RDF/OWL JSON-LD, knowledge-graph JSON, proof JSON, and
decompiler JSON.  Every export/import carries schema mappings, source-map
bindings, and explicit loss markers so consumers can distinguish a conformant
round trip from a useful but lossy projection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .legal_ir_diagnostics import (
    LegalIRDiagnosticCode,
    LegalIRDiagnosticReport,
    LegalIRDiagnosticSeverity,
    LegalIRDiagnosticsBuilder,
)
from .legal_ir_proof_carrying_artifacts import (
    LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
    LegalIRProofCarryingArtifact,
    validate_legal_ir_proof_carrying_artifact,
)
from .legal_ir_source_maps import (
    LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    validate_legal_ir_source_map,
)


LEGAL_IR_INTEROP_SCHEMA_VERSION: Final = "legal-ir-interop-v1"
LEGAL_IR_INTEROP_MAPPING_SCHEMA_VERSION: Final = "legal-ir-interop-mapping-v1"
LEGAL_IR_INTEROP_ROUND_TRIP_SCHEMA_VERSION: Final = "legal-ir-interop-round-trip-v1"

LEGAL_IR_XML_NAMESPACE: Final = "urn:legal-ir:interchange:v1"
LEGAL_IR_RDF_CONTEXT: Final[Mapping[str, str]] = {
    "lir": "urn:legal-ir:",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}


class LegalIRInteropError(ValueError):
    """Raised when an interchange payload is malformed or non-conformant."""


class LegalIRInteropDirection(str, Enum):
    """Direction for an interchange envelope."""

    EXPORT = "export"
    IMPORT = "import"


class LegalIRInteropFormat(str, Enum):
    """Selected LegalIR interchange profiles."""

    LEGAL_JSON = "legal_json"
    LEGAL_XML = "legal_xml"
    RDF_OWL_JSONLD = "rdf_owl_jsonld"
    KG_JSON = "kg_json"
    PROOF_JSON = "proof_json"
    DECOMPILER_JSON = "decompiler_json"


class LegalIRInteropLossMode(str, Enum):
    """Whether one mapping is lossless, lossy, or unsupported."""

    LOSSLESS = "lossless"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class LegalIRInteropSchemaMapping:
    """One field-level mapping between LegalIR and an interchange schema."""

    legal_ir_path: str
    interchange_path: str
    mode: str = LegalIRInteropLossMode.LOSSLESS.value
    feature: str = ""
    reason: str = ""
    source_node_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_INTEROP_MAPPING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _loss_mode(self.mode).value)
        object.__setattr__(self, "source_node_ids", _unique_text(self.source_node_ids))
        object.__setattr__(self, "source_span_ids", _unique_text(self.source_span_ids))
        object.__setattr__(self, "metadata", _mapping(self.metadata))

    @property
    def lossless(self) -> bool:
        return self.mode == LegalIRInteropLossMode.LOSSLESS.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "interchange_path": self.interchange_path,
            "legal_ir_path": self.legal_ir_path,
            "lossless": self.lossless,
            "metadata": _json_ready(self.metadata),
            "mode": self.mode,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "source_node_ids": list(self.source_node_ids),
            "source_span_ids": list(self.source_span_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRInteropSchemaMapping":
        return cls(
            legal_ir_path=str(data.get("legal_ir_path") or ""),
            interchange_path=str(data.get("interchange_path") or ""),
            mode=str(data.get("mode") or LegalIRInteropLossMode.LOSSLESS.value),
            feature=str(data.get("feature") or ""),
            reason=str(data.get("reason") or ""),
            source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
            source_span_ids=tuple(_strings(data.get("source_span_ids", ()))),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_INTEROP_MAPPING_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRInteropLossMarker:
    """Explicit lossy or unsupported projection marker."""

    legal_ir_path: str
    interchange_path: str
    mode: str
    reason: str
    format: str
    severity: str = LegalIRDiagnosticSeverity.WARNING.value
    marker_id: str = ""
    feature: str = ""
    source_node_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_INTEROP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        mode = _loss_mode(self.mode)
        payload = {
            "format": self.format,
            "interchange_path": self.interchange_path,
            "legal_ir_path": self.legal_ir_path,
            "mode": mode.value,
            "reason": self.reason,
        }
        object.__setattr__(self, "mode", mode.value)
        object.__setattr__(
            self,
            "severity",
            str(self.severity or LegalIRDiagnosticSeverity.WARNING.value).lower(),
        )
        object.__setattr__(
            self,
            "marker_id",
            self.marker_id or "lir-interop-loss-" + _stable_hash(payload)[:24],
        )
        object.__setattr__(self, "source_node_ids", _unique_text(self.source_node_ids))
        object.__setattr__(self, "source_span_ids", _unique_text(self.source_span_ids))
        object.__setattr__(self, "metadata", _mapping(self.metadata))

    @property
    def unsupported(self) -> bool:
        return self.mode == LegalIRInteropLossMode.UNSUPPORTED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "format": self.format,
            "interchange_path": self.interchange_path,
            "legal_ir_path": self.legal_ir_path,
            "marker_id": self.marker_id,
            "metadata": _json_ready(self.metadata),
            "mode": self.mode,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "severity": self.severity,
            "source_node_ids": list(self.source_node_ids),
            "source_span_ids": list(self.source_span_ids),
            "unsupported": self.unsupported,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRInteropLossMarker":
        return cls(
            legal_ir_path=str(data.get("legal_ir_path") or ""),
            interchange_path=str(data.get("interchange_path") or ""),
            mode=str(data.get("mode") or LegalIRInteropLossMode.LOSSY.value),
            reason=str(data.get("reason") or ""),
            format=str(data.get("format") or ""),
            severity=str(data.get("severity") or LegalIRDiagnosticSeverity.WARNING.value),
            marker_id=str(data.get("marker_id") or ""),
            feature=str(data.get("feature") or ""),
            source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
            source_span_ids=tuple(_strings(data.get("source_span_ids", ()))),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_INTEROP_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRInteropEnvelope:
    """A deterministic import/export interchange envelope."""

    format: str
    direction: str
    payload: Any
    legal_ir: Mapping[str, Any]
    schema_mappings: tuple[LegalIRInteropSchemaMapping, ...]
    loss_markers: tuple[LegalIRInteropLossMarker, ...] = ()
    diagnostics: LegalIRDiagnosticReport = field(
        default_factory=lambda: LegalIRDiagnosticReport(report_id="", diagnostics=())
    )
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None
    profile: str = ""
    envelope_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_INTEROP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        fmt = _format(self.format)
        direction = _direction(self.direction)
        mappings = tuple(
            item
            if isinstance(item, LegalIRInteropSchemaMapping)
            else LegalIRInteropSchemaMapping.from_dict(_mapping(item))
            for item in self.schema_mappings
        )
        losses = tuple(
            item
            if isinstance(item, LegalIRInteropLossMarker)
            else LegalIRInteropLossMarker.from_dict(_mapping(item))
            for item in self.loss_markers
        )
        diagnostics = (
            self.diagnostics
            if isinstance(self.diagnostics, LegalIRDiagnosticReport)
            else LegalIRDiagnosticReport.from_dict(_mapping(self.diagnostics))
        )
        source_map = self.source_map
        if source_map is not None and not isinstance(source_map, LegalIRSourceMap):
            source_map = LegalIRSourceMap.from_dict(_mapping(source_map))
        core = {
            "direction": direction.value,
            "format": fmt.value,
            "legal_ir_sha256": _stable_hash(self.legal_ir),
            "payload_sha256": _stable_hash(self.payload),
            "schema_version": self.schema_version,
        }
        object.__setattr__(self, "format", fmt.value)
        object.__setattr__(self, "direction", direction.value)
        object.__setattr__(self, "schema_mappings", mappings)
        object.__setattr__(self, "loss_markers", losses)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "source_map", source_map)
        object.__setattr__(self, "metadata", _mapping(self.metadata))
        object.__setattr__(
            self,
            "envelope_id",
            self.envelope_id or "lir-interop-envelope-" + _stable_hash(core)[:24],
        )

    @property
    def lossless(self) -> bool:
        return not self.loss_markers and all(mapping.lossless for mapping in self.schema_mappings)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for marker in self.loss_markers if marker.unsupported)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": self.diagnostics.to_dict(),
            "direction": self.direction,
            "envelope_id": self.envelope_id,
            "format": self.format,
            "legal_ir": _json_ready(self.legal_ir),
            "legal_ir_sha256": _stable_hash(self.legal_ir),
            "loss_markers": [marker.to_dict() for marker in self.loss_markers],
            "lossless": self.lossless,
            "metadata": _json_ready(self.metadata),
            "payload": _json_ready(self.payload),
            "payload_sha256": _stable_hash(self.payload),
            "profile": self.profile,
            "schema_mappings": [mapping.to_dict() for mapping in self.schema_mappings],
            "schema_version": self.schema_version,
            "source_map": self.source_map.to_dict() if isinstance(self.source_map, LegalIRSourceMap) else None,
            "source_map_schema_version": LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
            "unsupported_count": self.unsupported_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRInteropEnvelope":
        return cls(
            format=str(data.get("format") or ""),
            direction=str(data.get("direction") or LegalIRInteropDirection.EXPORT.value),
            payload=data.get("payload"),
            legal_ir=_mapping(data.get("legal_ir")),
            schema_mappings=tuple(
                LegalIRInteropSchemaMapping.from_dict(_mapping(item))
                for item in _sequence(data.get("schema_mappings"))
            ),
            loss_markers=tuple(
                LegalIRInteropLossMarker.from_dict(_mapping(item))
                for item in _sequence(data.get("loss_markers"))
            ),
            diagnostics=LegalIRDiagnosticReport.from_dict(_mapping(data.get("diagnostics"))),
            source_map=(
                LegalIRSourceMap.from_dict(_mapping(data.get("source_map")))
                if data.get("source_map") is not None
                else None
            ),
            profile=str(data.get("profile") or ""),
            envelope_id=str(data.get("envelope_id") or ""),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_INTEROP_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRInteropRoundTripResult:
    """Conformance proof for one import/export round trip."""

    format: str
    exported: LegalIRInteropEnvelope
    imported: LegalIRInteropEnvelope
    supported_before: Mapping[str, Any]
    supported_after: Mapping[str, Any]
    mismatches: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = LEGAL_IR_INTEROP_ROUND_TRIP_SCHEMA_VERSION

    @property
    def conformant(self) -> bool:
        return not self.mismatches and self.exported.diagnostics.valid and self.imported.diagnostics.valid

    @property
    def lossless(self) -> bool:
        return self.conformant and self.exported.lossless and self.imported.lossless

    def to_dict(self) -> dict[str, Any]:
        return {
            "conformant": self.conformant,
            "exported": self.exported.to_dict(),
            "format": self.format,
            "imported": self.imported.to_dict(),
            "lossless": self.lossless,
            "mismatches": [_json_ready(item) for item in self.mismatches],
            "schema_version": self.schema_version,
            "supported_after": _json_ready(self.supported_after),
            "supported_after_sha256": _stable_hash(self.supported_after),
            "supported_before": _json_ready(self.supported_before),
            "supported_before_sha256": _stable_hash(self.supported_before),
        }


def export_legal_ir_interchange(
    artifact: Mapping[str, Any] | str | LegalIRProofCarryingArtifact,
    target_format: LegalIRInteropFormat | str,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    profile: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRInteropEnvelope:
    """Export a LegalIR artifact to one selected interchange profile."""

    fmt = _format(target_format)
    legal_ir, resolved_source_map = _normalized_legal_ir(artifact, source_map=source_map)
    if resolved_source_map is None:
        resolved_source_map = _source_map_for_legal_ir(legal_ir)

    if fmt is LegalIRInteropFormat.LEGAL_JSON:
        payload, mappings, losses = _export_legal_json(legal_ir)
    elif fmt is LegalIRInteropFormat.LEGAL_XML:
        payload, mappings, losses = _export_legal_xml(legal_ir)
    elif fmt is LegalIRInteropFormat.RDF_OWL_JSONLD:
        payload, mappings, losses = _export_rdf_owl(legal_ir)
    elif fmt is LegalIRInteropFormat.KG_JSON:
        payload, mappings, losses = _export_kg(legal_ir)
    elif fmt is LegalIRInteropFormat.PROOF_JSON:
        payload, mappings, losses = _export_proof(legal_ir)
    elif fmt is LegalIRInteropFormat.DECOMPILER_JSON:
        payload, mappings, losses = _export_decompiler(legal_ir)
    else:  # pragma: no cover - enum guard
        raise LegalIRInteropError(f"Unsupported LegalIR interchange format: {target_format!r}")

    diagnostics = _diagnostics_from_losses(losses, source_map=resolved_source_map)
    return LegalIRInteropEnvelope(
        format=fmt.value,
        direction=LegalIRInteropDirection.EXPORT.value,
        payload=payload,
        legal_ir=legal_ir,
        schema_mappings=tuple(mappings),
        loss_markers=tuple(losses),
        diagnostics=diagnostics,
        source_map=resolved_source_map,
        profile=profile or _default_profile(fmt),
        metadata={"operation": "export", **dict(metadata or {})},
    )


def import_legal_ir_interchange(
    payload: Any,
    source_format: LegalIRInteropFormat | str | None = None,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    profile: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRInteropEnvelope:
    """Import one selected interchange payload into normalized LegalIR."""

    fmt = _format(source_format or _detect_format(payload))
    raw_payload = _payload_from_input(payload)
    if fmt is LegalIRInteropFormat.LEGAL_JSON:
        legal_ir, mappings, losses = _import_legal_json(raw_payload)
    elif fmt is LegalIRInteropFormat.LEGAL_XML:
        legal_ir, mappings, losses = _import_legal_xml(raw_payload)
    elif fmt is LegalIRInteropFormat.RDF_OWL_JSONLD:
        legal_ir, mappings, losses = _import_rdf_owl(raw_payload)
    elif fmt is LegalIRInteropFormat.KG_JSON:
        legal_ir, mappings, losses = _import_kg(raw_payload)
    elif fmt is LegalIRInteropFormat.PROOF_JSON:
        legal_ir, mappings, losses = _import_proof(raw_payload)
    elif fmt is LegalIRInteropFormat.DECOMPILER_JSON:
        legal_ir, mappings, losses = _import_decompiler(raw_payload)
    else:  # pragma: no cover - enum guard
        raise LegalIRInteropError(f"Unsupported LegalIR interchange format: {source_format!r}")

    resolved_source_map = _source_map(source_map) or _source_map_from_payload(raw_payload) or _source_map_for_legal_ir(legal_ir)
    diagnostics = _diagnostics_from_losses(losses, source_map=resolved_source_map)
    return LegalIRInteropEnvelope(
        format=fmt.value,
        direction=LegalIRInteropDirection.IMPORT.value,
        payload=raw_payload,
        legal_ir=legal_ir,
        schema_mappings=tuple(mappings),
        loss_markers=tuple(losses),
        diagnostics=diagnostics,
        source_map=resolved_source_map,
        profile=profile or _default_profile(fmt),
        metadata={"operation": "import", **dict(metadata or {})},
    )


def round_trip_legal_ir_interchange(
    artifact: Mapping[str, Any] | str | LegalIRProofCarryingArtifact,
    interchange_format: LegalIRInteropFormat | str,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    profile: str = "",
) -> LegalIRInteropRoundTripResult:
    """Export, import, and compare the supported subset for one format."""

    fmt = _format(interchange_format)
    exported = export_legal_ir_interchange(
        artifact,
        fmt,
        source_map=source_map,
        profile=profile,
        metadata={"round_trip_step": "export"},
    )
    imported = import_legal_ir_interchange(
        exported.payload,
        fmt,
        source_map=exported.source_map,
        profile=profile,
        metadata={"round_trip_step": "import"},
    )
    before = supported_legal_ir_projection(exported.legal_ir, fmt)
    after = supported_legal_ir_projection(imported.legal_ir, fmt)
    return LegalIRInteropRoundTripResult(
        format=fmt.value,
        exported=exported,
        imported=imported,
        supported_before=before,
        supported_after=after,
        mismatches=tuple(_diff_values(before, after)),
    )


def assert_legal_ir_interop_round_trip_conformant(
    artifact: Mapping[str, Any] | str | LegalIRProofCarryingArtifact,
    interchange_format: LegalIRInteropFormat | str,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    profile: str = "",
) -> LegalIRInteropRoundTripResult:
    """Return round-trip proof or raise with deterministic mismatch details."""

    result = round_trip_legal_ir_interchange(
        artifact,
        interchange_format,
        source_map=source_map,
        profile=profile,
    )
    if not result.conformant:
        raise LegalIRInteropError(
            "LegalIR interchange round trip is not conformant: "
            + json.dumps(result.to_dict()["mismatches"], sort_keys=True)
        )
    return result


def supported_legal_ir_projection(
    artifact: Mapping[str, Any] | LegalIRInteropEnvelope,
    interchange_format: LegalIRInteropFormat | str,
) -> dict[str, Any]:
    """Return the canonical LegalIR subset that the format claims to support."""

    fmt = _format(interchange_format)
    legal_ir = artifact.legal_ir if isinstance(artifact, LegalIRInteropEnvelope) else _normalized_legal_ir(artifact)[0]
    if fmt in {
        LegalIRInteropFormat.LEGAL_XML,
        LegalIRInteropFormat.RDF_OWL_JSONLD,
        LegalIRInteropFormat.KG_JSON,
    }:
        return {
            "citation": legal_ir.get("citation", ""),
            "document_id": legal_ir.get("document_id", ""),
            "obligations": [
                _projection_obligation(row)
                for row in _sequence(legal_ir.get("obligations"))
            ],
            "text": legal_ir.get("text", ""),
        }
    if fmt is LegalIRInteropFormat.PROOF_JSON:
        return {
            "legal_ir_outputs": _json_ready(legal_ir.get("legal_ir_outputs")),
            "proof": _json_ready(legal_ir.get("proof")),
            "proof_obligations": _json_ready(legal_ir.get("proof_obligations")),
        }
    if fmt is LegalIRInteropFormat.DECOMPILER_JSON:
        return {
            "decompiler": _json_ready(legal_ir.get("decompiler")),
            "obligations": [
                {
                    "formula_id": str(_mapping(row).get("formula_id") or ""),
                    "obligation_id": str(_mapping(row).get("obligation_id") or ""),
                    "statement": str(_mapping(row).get("statement") or ""),
                }
                for row in _sequence(legal_ir.get("obligations"))
            ],
            "text": legal_ir.get("text", ""),
        }
    return _json_ready(legal_ir)


def read_legal_ir_interchange_json(path: str | Path) -> LegalIRInteropEnvelope:
    """Load a serialized LegalIR interop envelope from JSON."""

    return LegalIRInteropEnvelope.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_legal_ir_interchange_json(
    path: str | Path,
    envelope: LegalIRInteropEnvelope | Mapping[str, Any],
    *,
    pretty: bool = True,
) -> None:
    """Write a LegalIR interop envelope as deterministic JSON."""

    payload = envelope.to_dict() if isinstance(envelope, LegalIRInteropEnvelope) else _mapping(envelope)
    Path(path).write_text(
        json.dumps(
            _json_ready(payload),
            allow_nan=False,
            ensure_ascii=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _export_legal_json(
    legal_ir: Mapping[str, Any],
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    mappings = [_mapping_lossless("$", "$.legal_ir", "legal_json")]
    payload = {
        "legal_ir": _json_ready(legal_ir),
        "profile": _default_profile(LegalIRInteropFormat.LEGAL_JSON),
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
    }
    return payload, mappings, []


def _import_legal_json(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    data = _mapping(payload)
    legal_ir = _mapping(data.get("legal_ir") if "legal_ir" in data else data)
    mappings = [_mapping_lossless("$.legal_ir", "$", "legal_json")]
    return _canonical_legal_ir(legal_ir), mappings, []


def _export_legal_xml(
    legal_ir: Mapping[str, Any],
) -> tuple[str, list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    root = ET.Element(
        "LegalDocument",
        {
            "xmlns": LEGAL_IR_XML_NAMESPACE,
            "documentId": str(legal_ir.get("document_id") or ""),
            "schemaVersion": LEGAL_IR_INTEROP_SCHEMA_VERSION,
        },
    )
    ET.SubElement(root, "Citation").text = str(legal_ir.get("citation") or "")
    ET.SubElement(root, "Text").text = str(legal_ir.get("text") or "")
    obligations_el = ET.SubElement(root, "Obligations")
    mappings = [
        _mapping_lossless("$.document_id", "/LegalDocument/@documentId", "legal_xml"),
        _mapping_lossless("$.citation", "/LegalDocument/Citation", "legal_xml"),
        _mapping_lossless("$.text", "/LegalDocument/Text", "legal_xml"),
        _mapping_lossless("$.obligations", "/LegalDocument/Obligations", "legal_xml"),
    ]
    for index, obligation in enumerate(_sequence(legal_ir.get("obligations"))):
        row = _mapping(obligation)
        element = ET.SubElement(
            obligations_el,
            "Obligation",
            {
                "id": str(row.get("obligation_id") or ""),
                "formulaId": str(row.get("formula_id") or ""),
                "operator": str(row.get("operator") or ""),
            },
        )
        for key in ("statement", "subject", "action", "object", "conditions", "exceptions", "citations", "proof_status", "metadata"):
            child = ET.SubElement(element, _camel_tag(key))
            value = row.get(key)
            child.text = json.dumps(_json_ready(value), allow_nan=False, ensure_ascii=True, sort_keys=True)
        mappings.append(
            _mapping_lossless(
                f"$.obligations[{index}]",
                f"/LegalDocument/Obligations/Obligation[{index + 1}]",
                "legal_xml",
                source_node_ids=_strings(row.get("source_node_ids", ())),
            )
        )
    losses = _unsupported_top_level(
        legal_ir,
        LegalIRInteropFormat.LEGAL_XML,
        supported={
            "citation",
            "document_id",
            "obligations",
            "schema_version",
            "source_map_id",
            "text",
        },
    )
    xml_text = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return xml_text, mappings, losses


def _import_legal_xml(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    text = payload if isinstance(payload, str) else str(payload or "")
    if not text.strip():
        raise LegalIRInteropError("Legal XML interchange payload is empty.")
    root = ET.fromstring(text)
    ns = _xml_namespace(root.tag)
    document_id = str(root.attrib.get("documentId") or root.attrib.get("document_id") or "")
    citation = _xml_text(root, "Citation", ns)
    document_text = _xml_text(root, "Text", ns)
    obligations: list[dict[str, Any]] = []
    obligations_el = root.find(_xml_name("Obligations", ns))
    if obligations_el is not None:
        for element in obligations_el.findall(_xml_name("Obligation", ns)):
            row = {
                "action": _json_child(element, "Action", ns, []),
                "citations": _json_child(element, "Citations", ns, []),
                "conditions": _json_child(element, "Conditions", ns, []),
                "exceptions": _json_child(element, "Exceptions", ns, []),
                "formula_id": str(element.attrib.get("formulaId") or ""),
                "metadata": _json_child(element, "Metadata", ns, {}),
                "object": _json_child(element, "Object", ns, []),
                "obligation_id": str(element.attrib.get("id") or ""),
                "operator": str(element.attrib.get("operator") or ""),
                "proof_status": _json_child(element, "ProofStatus", ns, {}),
                "statement": str(_json_child(element, "Statement", ns, "")),
                "subject": _json_child(element, "Subject", ns, []),
            }
            obligations.append(_normalize_obligation(row, len(obligations)))
    legal_ir = _canonical_legal_ir(
        {
            "citation": citation,
            "document_id": document_id,
            "obligations": obligations,
            "text": document_text,
        }
    )
    mappings = [
        _mapping_lossless("/LegalDocument/@documentId", "$.document_id", "legal_xml"),
        _mapping_lossless("/LegalDocument/Citation", "$.citation", "legal_xml"),
        _mapping_lossless("/LegalDocument/Text", "$.text", "legal_xml"),
        _mapping_lossless("/LegalDocument/Obligations", "$.obligations", "legal_xml"),
    ]
    return legal_ir, mappings, []


def _export_rdf_owl(
    legal_ir: Mapping[str, Any],
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    graph: list[dict[str, Any]] = [
        {
            "@id": "lir:LegalDocument",
            "@type": "owl:Class",
            "rdfs:label": "LegalIR document",
        },
        {
            "@id": "lir:Obligation",
            "@type": "owl:Class",
            "rdfs:label": "LegalIR obligation",
        },
        {
            "@id": _rdf_id("document", str(legal_ir.get("document_id") or "document")),
            "@type": "lir:LegalDocument",
            "lir:citation": str(legal_ir.get("citation") or ""),
            "lir:documentId": str(legal_ir.get("document_id") or ""),
            "lir:text": str(legal_ir.get("text") or ""),
        },
    ]
    mappings = [
        _mapping_lossless("$.document_id", "@graph[lir:document].lir:documentId", "rdf_owl"),
        _mapping_lossless("$.citation", "@graph[lir:document].lir:citation", "rdf_owl"),
        _mapping_lossless("$.text", "@graph[lir:document].lir:text", "rdf_owl"),
    ]
    for index, obligation in enumerate(_sequence(legal_ir.get("obligations"))):
        row = _mapping(obligation)
        graph.append(
            {
                "@id": _rdf_id("obligation", str(row.get("obligation_id") or f"obligation-{index + 1}")),
                "@type": "lir:Obligation",
                "lir:action": _json_ready(row.get("action")),
                "lir:citation": _json_ready(row.get("citations")),
                "lir:condition": _json_ready(row.get("conditions")),
                "lir:exception": _json_ready(row.get("exceptions")),
                "lir:formulaId": str(row.get("formula_id") or ""),
                "lir:hasSourceNode": _json_ready(row.get("source_node_ids")),
                "lir:object": _json_ready(row.get("object")),
                "lir:obligationId": str(row.get("obligation_id") or ""),
                "lir:operator": str(row.get("operator") or ""),
                "lir:proofStatus": _json_ready(row.get("proof_status")),
                "lir:statement": str(row.get("statement") or ""),
                "lir:subject": _json_ready(row.get("subject")),
            }
        )
        mappings.append(
            _mapping_lossless(
                f"$.obligations[{index}]",
                f"@graph[lir:obligation/{row.get('obligation_id')}]",
                "rdf_owl",
                source_node_ids=_strings(row.get("source_node_ids", ())),
            )
        )
    payload = {
        "@context": dict(LEGAL_IR_RDF_CONTEXT),
        "@graph": graph,
        "ontology": {
            "classes": ["lir:LegalDocument", "lir:Obligation"],
            "object_properties": ["lir:hasObligation", "lir:hasSourceNode"],
            "profile": _default_profile(LegalIRInteropFormat.RDF_OWL_JSONLD),
        },
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
    }
    losses = _unsupported_top_level(
        legal_ir,
        LegalIRInteropFormat.RDF_OWL_JSONLD,
        supported={"citation", "document_id", "obligations", "schema_version", "source_map_id", "text"},
    )
    return payload, mappings, losses


def _import_rdf_owl(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    data = _mapping(payload)
    graph = [_mapping(item) for item in _sequence(data.get("@graph"))]
    document = next((node for node in graph if node.get("@type") == "lir:LegalDocument"), {})
    obligations = []
    for node in graph:
        if node.get("@type") != "lir:Obligation":
            continue
        obligations.append(
            _normalize_obligation(
                {
                    "action": _list_value(node.get("lir:action")),
                    "citations": _list_value(node.get("lir:citation")),
                    "conditions": _list_value(node.get("lir:condition")),
                    "exceptions": _list_value(node.get("lir:exception")),
                    "formula_id": str(node.get("lir:formulaId") or ""),
                    "object": _list_value(node.get("lir:object")),
                    "obligation_id": str(node.get("lir:obligationId") or ""),
                    "operator": str(node.get("lir:operator") or ""),
                    "proof_status": _mapping(node.get("lir:proofStatus")),
                    "source_node_ids": _list_value(node.get("lir:hasSourceNode")),
                    "statement": str(node.get("lir:statement") or ""),
                    "subject": _list_value(node.get("lir:subject")),
                },
                len(obligations),
            )
        )
    legal_ir = _canonical_legal_ir(
        {
            "citation": str(document.get("lir:citation") or ""),
            "document_id": str(document.get("lir:documentId") or ""),
            "obligations": obligations,
            "text": str(document.get("lir:text") or ""),
        }
    )
    mappings = [
        _mapping_lossless("@graph[lir:document].lir:documentId", "$.document_id", "rdf_owl"),
        _mapping_lossless("@graph[lir:document].lir:citation", "$.citation", "rdf_owl"),
        _mapping_lossless("@graph[lir:document].lir:text", "$.text", "rdf_owl"),
        _mapping_lossless("@graph[lir:Obligation]", "$.obligations", "rdf_owl"),
    ]
    return legal_ir, mappings, []


def _export_kg(
    legal_ir: Mapping[str, Any],
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    document_id = str(legal_ir.get("document_id") or "legal-ir-document")
    nodes: list[dict[str, Any]] = [
        {
            "id": f"document:{document_id}",
            "kind": "legal_document",
            "properties": {
                "citation": str(legal_ir.get("citation") or ""),
                "document_id": document_id,
                "text": str(legal_ir.get("text") or ""),
            },
        }
    ]
    edges: list[dict[str, Any]] = []
    mappings = [
        _mapping_lossless("$.document_id", "$.nodes[document].properties.document_id", "kg"),
        _mapping_lossless("$.obligations", "$.nodes[kind=obligation]", "kg"),
    ]
    for index, obligation in enumerate(_sequence(legal_ir.get("obligations"))):
        row = _mapping(obligation)
        obligation_id = str(row.get("obligation_id") or f"obligation-{index + 1}")
        nodes.append(
            {
                "id": f"obligation:{obligation_id}",
                "kind": "obligation",
                "properties": _json_ready(_projection_obligation(row)),
            }
        )
        edges.append(
            {
                "from": f"document:{document_id}",
                "kind": "has_obligation",
                "to": f"obligation:{obligation_id}",
            }
        )
        for citation in _strings(row.get("citations", ())):
            citation_id = "citation:" + _slug(citation)
            nodes.append({"id": citation_id, "kind": "citation", "properties": {"citation": citation}})
            edges.append({"from": f"obligation:{obligation_id}", "kind": "cites", "to": citation_id})
    existing_kg = _mapping(legal_ir.get("kg"))
    if existing_kg:
        nodes.extend(_mapping(item) for item in _sequence(existing_kg.get("nodes")))
        edges.extend(_mapping(item) for item in _sequence(existing_kg.get("edges")))
        mappings.append(_mapping_lossless("$.kg", "$.extensions.source_kg", "kg"))
    payload = {
        "directed": True,
        "edges": _dedupe_dicts(edges),
        "nodes": _dedupe_dicts(nodes),
        "profile": _default_profile(LegalIRInteropFormat.KG_JSON),
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
    }
    losses = _unsupported_top_level(
        legal_ir,
        LegalIRInteropFormat.KG_JSON,
        supported={"citation", "document_id", "kg", "obligations", "schema_version", "source_map_id", "text"},
    )
    return payload, mappings, losses


def _import_kg(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    data = _mapping(payload)
    nodes = [_mapping(item) for item in _sequence(data.get("nodes"))]
    document_node = next((node for node in nodes if node.get("kind") == "legal_document"), {})
    document_props = _mapping(document_node.get("properties"))
    obligations = []
    for node in nodes:
        if node.get("kind") != "obligation":
            continue
        obligations.append(_normalize_obligation(_mapping(node.get("properties")), len(obligations)))
    legal_ir = _canonical_legal_ir(
        {
            "citation": str(document_props.get("citation") or ""),
            "document_id": str(document_props.get("document_id") or ""),
            "kg": {"edges": _sequence(data.get("edges")), "nodes": nodes},
            "obligations": obligations,
            "text": str(document_props.get("text") or ""),
        }
    )
    mappings = [
        _mapping_lossless("$.nodes[document].properties.document_id", "$.document_id", "kg"),
        _mapping_lossless("$.nodes[kind=obligation]", "$.obligations", "kg"),
    ]
    return legal_ir, mappings, []


def _export_proof(
    legal_ir: Mapping[str, Any],
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    proof = _mapping(legal_ir.get("proof"))
    payload = {
        "artifact_id": proof.get("artifact_id", ""),
        "evidence": _json_ready(proof.get("evidence", {})),
        "legal_ir_outputs": _json_ready(legal_ir.get("legal_ir_outputs")),
        "proof_obligations": _json_ready(legal_ir.get("proof_obligations")),
        "profile": _default_profile(LegalIRInteropFormat.PROOF_JSON),
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
        "verification_policy": _json_ready(proof.get("verification_policy", {})),
    }
    mappings = [
        _mapping_lossless("$.proof_obligations", "$.proof_obligations", "proof"),
        _mapping_lossless("$.proof", "$.evidence", "proof"),
        _mapping_lossless("$.legal_ir_outputs", "$.legal_ir_outputs", "proof"),
    ]
    losses = _unsupported_top_level(
        legal_ir,
        LegalIRInteropFormat.PROOF_JSON,
        supported={
            "legal_ir_outputs",
            "proof",
            "proof_obligations",
            "schema_version",
            "source_map_id",
        },
    )
    return payload, mappings, losses


def _import_proof(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    data = _mapping(payload)
    proof = {
        "artifact_id": str(data.get("artifact_id") or ""),
        "evidence": _mapping(data.get("evidence")),
        "verification_policy": _mapping(data.get("verification_policy")),
    }
    legal_ir = _canonical_legal_ir(
        {
            "legal_ir_outputs": _mapping(data.get("legal_ir_outputs")),
            "proof": proof,
            "proof_obligations": _sequence(data.get("proof_obligations")),
        }
    )
    mappings = [
        _mapping_lossless("$.proof_obligations", "$.proof_obligations", "proof"),
        _mapping_lossless("$.evidence", "$.proof", "proof"),
        _mapping_lossless("$.legal_ir_outputs", "$.legal_ir_outputs", "proof"),
    ]
    return legal_ir, mappings, []


def _export_decompiler(
    legal_ir: Mapping[str, Any],
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    decompiler = _mapping(legal_ir.get("decompiler"))
    statements = _strings(decompiler.get("statements", ())) or [
        str(_mapping(row).get("statement") or "")
        for row in _sequence(legal_ir.get("obligations"))
        if str(_mapping(row).get("statement") or "")
    ]
    text = str(decompiler.get("decompiled_text") or legal_ir.get("text") or "\n".join(statements))
    payload = {
        "decompiled_text": text,
        "losses": _json_ready(decompiler.get("losses", ())),
        "lossless": bool(decompiler.get("lossless", not decompiler.get("losses"))),
        "obligation_statements": [
            {
                "formula_id": str(_mapping(row).get("formula_id") or ""),
                "obligation_id": str(_mapping(row).get("obligation_id") or ""),
                "statement": str(_mapping(row).get("statement") or ""),
            }
            for row in _sequence(legal_ir.get("obligations"))
        ],
        "profile": _default_profile(LegalIRInteropFormat.DECOMPILER_JSON),
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
        "statements": statements,
    }
    mappings = [
        _mapping_lossless("$.decompiler", "$", "decompiler"),
        _mapping_lossless("$.obligations[*].statement", "$.obligation_statements", "decompiler"),
    ]
    losses = _unsupported_top_level(
        legal_ir,
        LegalIRInteropFormat.DECOMPILER_JSON,
        supported={"decompiler", "obligations", "schema_version", "source_map_id", "text"},
    )
    for item in _sequence(decompiler.get("losses")):
        loss = _mapping(item)
        if loss:
            losses.append(
                LegalIRInteropLossMarker(
                    legal_ir_path=str(loss.get("field_path") or "$.decompiler"),
                    interchange_path="$.losses",
                    mode=LegalIRInteropLossMode.LOSSY.value,
                    reason=str(loss.get("reason") or "decompiler_loss"),
                    format=LegalIRInteropFormat.DECOMPILER_JSON.value,
                    feature="decompiler_round_trip",
                    metadata=loss,
                )
            )
    return payload, mappings, losses


def _import_decompiler(
    payload: Any,
) -> tuple[dict[str, Any], list[LegalIRInteropSchemaMapping], list[LegalIRInteropLossMarker]]:
    data = _mapping(payload)
    statements = _strings(data.get("statements", ())) or [
        str(_mapping(row).get("statement") or "")
        for row in _sequence(data.get("obligation_statements"))
        if str(_mapping(row).get("statement") or "")
    ]
    obligations = [
        _normalize_obligation(row, index)
        for index, row in enumerate(_sequence(data.get("obligation_statements")))
    ]
    if not obligations:
        obligations = [
            _normalize_obligation({"statement": statement}, index)
            for index, statement in enumerate(statements)
        ]
    losses = [
        LegalIRInteropLossMarker(
            legal_ir_path=str(_mapping(item).get("field_path") or "$.decompiler"),
            interchange_path="$.losses",
            mode=LegalIRInteropLossMode.LOSSY.value,
            reason=str(_mapping(item).get("reason") or "decompiler_loss"),
            format=LegalIRInteropFormat.DECOMPILER_JSON.value,
            feature="decompiler_round_trip",
            metadata=_mapping(item),
        )
        for item in _sequence(data.get("losses"))
        if _mapping(item)
    ]
    legal_ir = _canonical_legal_ir(
        {
            "decompiler": {
                "decompiled_text": str(data.get("decompiled_text") or "\n".join(statements)),
                "losses": _sequence(data.get("losses")),
                "lossless": bool(data.get("lossless", not losses)),
                "statements": statements,
            },
            "obligations": obligations,
            "text": str(data.get("decompiled_text") or "\n".join(statements)),
        }
    )
    mappings = [
        _mapping_lossless("$", "$.decompiler", "decompiler"),
        _mapping_lossless("$.obligation_statements", "$.obligations[*].statement", "decompiler"),
    ]
    return legal_ir, mappings, losses


def _normalized_legal_ir(
    artifact: Mapping[str, Any] | str | LegalIRProofCarryingArtifact,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], LegalIRSourceMap | None]:
    payload = _payload_from_input(artifact)
    if isinstance(artifact, LegalIRProofCarryingArtifact):
        payload = artifact.to_dict()
    if str(_mapping(payload).get("schema_version") or "") == LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION:
        proof_artifact = LegalIRProofCarryingArtifact.from_dict(_mapping(payload))
        validation = validate_legal_ir_proof_carrying_artifact(
            proof_artifact,
            policy={
                "require_build_manifest": False,
                "require_hammer_guidance": False,
                "require_hammer_receipts": False,
                "require_source_map": False,
                "require_source_traceability": False,
                "require_translation_records": False,
            },
        )
        payload = {
            **proof_artifact.to_dict(),
            "legal_ir_outputs": proof_artifact.legal_ir_outputs,
            "proof": {
                "artifact_id": proof_artifact.artifact_id,
                "evidence": {
                    "diagnostics": [item.to_dict() for item in proof_artifact.diagnostics],
                    "evidence_bindings": [item.to_dict() for item in proof_artifact.evidence_bindings],
                    "hammer_guidance_artifacts": [item.to_dict() for item in proof_artifact.hammer_guidance_artifacts],
                    "reconstruction_receipts": [item.to_dict() for item in proof_artifact.reconstruction_receipts],
                    "route_results": [_json_ready(item) for item in proof_artifact.route_results],
                    "translation_records": [item.to_dict() for item in proof_artifact.translation_records],
                    "unsupported_diagnostics": [item.to_dict() for item in proof_artifact.unsupported_diagnostics],
                    "validation": validation.to_dict(),
                },
                "verification_policy": proof_artifact.verification_policy.to_dict(),
            },
            "proof_obligations": [item.to_dict() for item in proof_artifact.proof_obligations],
        }
    payload = _compiled_payload(_mapping(payload))
    resolved_source_map = _source_map(source_map) or _source_map_from_payload(payload)
    return _canonical_legal_ir(payload, source_map=resolved_source_map), resolved_source_map


def _canonical_legal_ir(
    payload: Mapping[str, Any],
    *,
    source_map: LegalIRSourceMap | None = None,
) -> dict[str, Any]:
    data = _mapping(payload)
    normalized_document = _mapping(data.get("normalized_document"))
    resolved_source_map = source_map or _source_map_from_payload(data)
    first_source = resolved_source_map.sources[0] if resolved_source_map and resolved_source_map.sources else None
    text = str(
        data.get("text")
        or data.get("raw_document")
        or data.get("normalized_text")
        or normalized_document.get("normalized_text")
        or data.get("decompiled_text")
        or (first_source.normalized_text if first_source else "")
        or ""
    )
    citation = str(
        data.get("citation")
        or normalized_document.get("citation")
        or (first_source.citation if first_source else "")
        or ""
    )
    document_id = str(
        data.get("document_id")
        or data.get("source_document_id")
        or normalized_document.get("source_document_id")
        or (first_source.source_document_id if first_source else "")
        or ""
    )
    obligations = [
        _normalize_obligation(item, index, default_citation=citation)
        for index, item in enumerate(_sequence(data.get("obligations")))
    ]
    proof_obligations = [_mapping(item) for item in _sequence(data.get("proof_obligations"))]
    if not obligations and proof_obligations:
        obligations = [
            _normalize_obligation(item, index, default_citation=citation)
            for index, item in enumerate(proof_obligations)
        ]
    decompiler = _mapping(data.get("decompiler"))
    if not decompiler and (data.get("decompiled_text") or data.get("statements") or data.get("decompiler_losses")):
        decompiler = {
            "decompiled_text": str(data.get("decompiled_text") or ""),
            "losses": _sequence(data.get("decompiler_losses")),
            "lossless": not _sequence(data.get("decompiler_losses")),
            "statements": _strings(data.get("statements", ())),
        }
    result = {
        "citation": citation,
        "decompiler": _json_ready(decompiler),
        "document_id": document_id,
        "kg": _json_ready(_mapping(data.get("kg")) or _mapping(data.get("knowledge_graph"))),
        "legal_ir_outputs": _json_ready(_mapping(data.get("legal_ir_outputs"))),
        "obligations": [_json_ready(row) for row in obligations],
        "proof": _json_ready(_mapping(data.get("proof"))),
        "proof_obligations": _json_ready(proof_obligations),
        "schema_version": LEGAL_IR_INTEROP_SCHEMA_VERSION,
        "source_map_id": resolved_source_map.source_map_id if resolved_source_map else str(data.get("source_map_id") or ""),
        "text": text,
    }
    return _drop_empty(result)


def _normalize_obligation(
    item: Any,
    index: int,
    *,
    default_citation: str = "",
) -> dict[str, Any]:
    row = _mapping(item)
    if not row and isinstance(item, str):
        row = {"statement": item}
    statement = str(row.get("statement") or row.get("text") or "")
    obligation_id = str(row.get("obligation_id") or row.get("id") or f"obligation-{index + 1:04d}")
    formula_id = str(row.get("formula_id") or row.get("formula") or f"formula-{obligation_id}")
    citations = _strings(row.get("citations", ())) or ([default_citation] if default_citation else [])
    metadata = {
        str(key): value
        for key, value in row.items()
        if key
        not in {
            "action",
            "citations",
            "conditions",
            "exceptions",
            "formula",
            "formula_id",
            "id",
            "metadata",
            "object",
            "obligation_id",
            "operator",
            "proof_status",
            "source_node_ids",
            "statement",
            "subject",
            "text",
        }
    }
    metadata.update(_mapping(row.get("metadata")))
    return _drop_empty(
        {
            "action": _list_value(row.get("action")),
            "citations": citations,
            "conditions": _list_value(row.get("conditions")),
            "exceptions": _list_value(row.get("exceptions")),
            "formula_id": formula_id,
            "metadata": _json_ready(metadata),
            "object": _list_value(row.get("object")),
            "obligation_id": obligation_id,
            "operator": str(row.get("operator") or _operator_from_statement(statement)),
            "proof_status": _json_ready(_mapping(row.get("proof_status"))),
            "source_node_ids": _strings(row.get("source_node_ids", ())) or ([formula_id] if formula_id else []),
            "statement": statement,
            "subject": _list_value(row.get("subject")),
        }
    )


def _projection_obligation(item: Mapping[str, Any]) -> dict[str, Any]:
    row = _mapping(item)
    return _drop_empty(
        {
            "action": _list_value(row.get("action")),
            "citations": _strings(row.get("citations", ())),
            "conditions": _list_value(row.get("conditions")),
            "exceptions": _list_value(row.get("exceptions")),
            "formula_id": str(row.get("formula_id") or ""),
            "object": _list_value(row.get("object")),
            "obligation_id": str(row.get("obligation_id") or ""),
            "operator": str(row.get("operator") or ""),
            "proof_status": _mapping(row.get("proof_status")),
            "source_node_ids": _strings(row.get("source_node_ids", ())),
            "statement": str(row.get("statement") or ""),
            "subject": _list_value(row.get("subject")),
        }
    )


def _unsupported_top_level(
    legal_ir: Mapping[str, Any],
    fmt: LegalIRInteropFormat,
    *,
    supported: set[str],
) -> list[LegalIRInteropLossMarker]:
    losses: list[LegalIRInteropLossMarker] = []
    for key, value in sorted(legal_ir.items()):
        if key in supported or _empty(value):
            continue
        losses.append(
            LegalIRInteropLossMarker(
                legal_ir_path=f"$.{key}",
                interchange_path="$",
                mode=LegalIRInteropLossMode.UNSUPPORTED.value,
                reason=f"{fmt.value} selected profile does not carry LegalIR field {key!r}.",
                format=fmt.value,
                feature=key,
                metadata={"field": key},
            )
        )
    return losses


def _diagnostics_from_losses(
    losses: Sequence[LegalIRInteropLossMarker],
    *,
    source_map: LegalIRSourceMap | None,
) -> LegalIRDiagnosticReport:
    builder = LegalIRDiagnosticsBuilder(
        artifact_id="legal-ir-interop",
        source_map=source_map,
        metadata={"source": "legal_ir_interop"},
    )
    for marker in losses:
        if marker.unsupported:
            builder.add_unsupported_backend_feature(
                marker.reason,
                severity=marker.severity,
                field_path=marker.legal_ir_path,
                related_ids={
                    "format": (marker.format,),
                    "marker_id": (marker.marker_id,),
                    "feature": (marker.feature,),
                },
                metadata=marker.to_dict(),
            )
        else:
            builder.add_decompiler_loss(
                marker.reason,
                severity=marker.severity,
                field_path=marker.legal_ir_path,
                related_ids={"marker_id": (marker.marker_id,), "format": (marker.format,)},
                metadata=marker.to_dict(),
            )
    if source_map is not None:
        validation = validate_legal_ir_source_map(source_map)
        for issue in validation.issues:
            severity = (
                LegalIRDiagnosticSeverity.ERROR
                if str(issue.severity or "").lower() == "error"
                else LegalIRDiagnosticSeverity.WARNING
            )
            builder.add(
                LegalIRDiagnosticCode.SOURCE_MAP_UNTRACEABLE,
                issue.message,
                severity=severity,
                field_path=issue.field_path,
                related_ids={
                    "source_map_id": (source_map.source_map_id,),
                    "source_map_issue": (issue.code,),
                },
                metadata=issue.to_dict(),
            )
    return builder.build()


def _source_map_for_legal_ir(legal_ir: Mapping[str, Any]) -> LegalIRSourceMap | None:
    text = str(legal_ir.get("text") or "")
    if not text:
        return None
    document_id = str(legal_ir.get("document_id") or "legal-ir-interop-source")
    citation = str(legal_ir.get("citation") or f"uncited:{document_id}")
    builder = LegalIRSourceMapBuilder(
        source_map_id="lir-interop-source-map-" + _stable_hash(
            {"citation": citation, "document_id": document_id, "text": text}
        )[:24],
        metadata={"builder": "legal_ir_interop"},
    )
    builder.add_source_document(document_id, text, citation=citation)
    span = builder.add_span(
        document_id,
        0,
        len(text),
        transformation_step_id="interop.ingest",
    )
    root_id = "document-" + _stable_hash({"document_id": document_id, "text": text})[:16]
    builder.add_node(
        root_id,
        node_kind="legal_document",
        span_ids=(span.span_id,),
        emitted_fact=root_id,
        transformation_step_id="interop.ingest",
    )
    for obligation in _sequence(legal_ir.get("obligations")):
        row = _mapping(obligation)
        formula_id = str(row.get("formula_id") or row.get("obligation_id") or "")
        if not formula_id:
            continue
        if not builder.has_node(formula_id):
            builder.add_derived_node(
                formula_id,
                node_kind="interop_obligation",
                derived_from_node_ids=(root_id,),
                transformation_step="interop.normalize_obligation",
                transform_kind=LegalIRTransformationKind.NORMALIZATION,
                emitted_fact=formula_id,
            )
    return builder.to_source_map()


def _source_map_from_payload(payload: Any) -> LegalIRSourceMap | None:
    data = _mapping(payload)
    source_map = data.get("source_map")
    if source_map is None and isinstance(data.get("payload"), Mapping):
        source_map = _mapping(data.get("payload")).get("source_map")
    if source_map is None:
        return None
    if isinstance(source_map, LegalIRSourceMap):
        return source_map
    mapped = _mapping(source_map)
    if not mapped:
        return None
    return LegalIRSourceMap.from_dict(mapped)


def _compiled_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(payload)
    if isinstance(data.get("compiled"), Mapping):
        return _mapping(data.get("compiled"))
    if isinstance(data.get("payload"), Mapping):
        nested = _mapping(data.get("payload"))
        if isinstance(nested.get("compiled"), Mapping):
            return _mapping(nested.get("compiled"))
        if isinstance(nested.get("artifact"), Mapping):
            return _mapping(nested.get("artifact"))
    return data


def _payload_from_input(value: Any) -> Any:
    if isinstance(value, LegalIRInteropEnvelope):
        return value.payload
    if isinstance(value, LegalIRProofCarryingArtifact):
        return value.to_dict()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(stripped)
        if stripped.startswith("<"):
            return value
        path = Path(value)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"text": value}
    return value


def _mapping_lossless(
    legal_ir_path: str,
    interchange_path: str,
    feature: str,
    *,
    source_node_ids: Sequence[str] = (),
    source_span_ids: Sequence[str] = (),
) -> LegalIRInteropSchemaMapping:
    return LegalIRInteropSchemaMapping(
        legal_ir_path=legal_ir_path,
        interchange_path=interchange_path,
        mode=LegalIRInteropLossMode.LOSSLESS.value,
        feature=feature,
        source_node_ids=tuple(source_node_ids),
        source_span_ids=tuple(source_span_ids),
    )


def _diff_values(before: Any, after: Any, *, path: str = "$") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        mismatches: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after), key=str):
            mismatches.extend(_diff_values(before.get(key), after.get(key), path=f"{path}.{key}"))
        return mismatches
    if isinstance(before, Sequence) and isinstance(after, Sequence) and not isinstance(before, (str, bytes, bytearray)):
        mismatches = []
        for index in range(max(len(before), len(after))):
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            mismatches.extend(_diff_values(left, right, path=f"{path}[{index}]"))
        return mismatches
    return [{"after": _json_ready(after), "before": _json_ready(before), "path": path}]


def _detect_format(payload: Any) -> str:
    raw = _payload_from_input(payload)
    if isinstance(raw, str) and raw.strip().startswith("<"):
        return LegalIRInteropFormat.LEGAL_XML.value
    data = _mapping(raw)
    if data.get("@graph"):
        return LegalIRInteropFormat.RDF_OWL_JSONLD.value
    if "nodes" in data and "edges" in data:
        return LegalIRInteropFormat.KG_JSON.value
    if "proof_obligations" in data and ("evidence" in data or "verification_policy" in data):
        return LegalIRInteropFormat.PROOF_JSON.value
    if "decompiled_text" in data or "obligation_statements" in data:
        return LegalIRInteropFormat.DECOMPILER_JSON.value
    return LegalIRInteropFormat.LEGAL_JSON.value


def _format(value: LegalIRInteropFormat | str) -> LegalIRInteropFormat:
    if isinstance(value, LegalIRInteropFormat):
        return value
    token = _token(value)
    aliases = {
        "akoma_ntoso": LegalIRInteropFormat.LEGAL_XML.value,
        "akn": LegalIRInteropFormat.LEGAL_XML.value,
        "json": LegalIRInteropFormat.LEGAL_JSON.value,
        "jsonld": LegalIRInteropFormat.RDF_OWL_JSONLD.value,
        "kg": LegalIRInteropFormat.KG_JSON.value,
        "knowledge_graph": LegalIRInteropFormat.KG_JSON.value,
        "legal_json": LegalIRInteropFormat.LEGAL_JSON.value,
        "legal_xml": LegalIRInteropFormat.LEGAL_XML.value,
        "owl": LegalIRInteropFormat.RDF_OWL_JSONLD.value,
        "proof": LegalIRInteropFormat.PROOF_JSON.value,
        "rdf": LegalIRInteropFormat.RDF_OWL_JSONLD.value,
        "rdf_owl": LegalIRInteropFormat.RDF_OWL_JSONLD.value,
        "rdf_owl_jsonld": LegalIRInteropFormat.RDF_OWL_JSONLD.value,
        "xml": LegalIRInteropFormat.LEGAL_XML.value,
    }
    resolved = aliases.get(token, str(value or ""))
    try:
        return LegalIRInteropFormat(resolved)
    except ValueError as exc:
        raise LegalIRInteropError(f"Unknown LegalIR interchange format: {value!r}") from exc


def _direction(value: LegalIRInteropDirection | str) -> LegalIRInteropDirection:
    if isinstance(value, LegalIRInteropDirection):
        return value
    try:
        return LegalIRInteropDirection(str(value or ""))
    except ValueError as exc:
        raise LegalIRInteropError(f"Unknown LegalIR interop direction: {value!r}") from exc


def _loss_mode(value: LegalIRInteropLossMode | str) -> LegalIRInteropLossMode:
    if isinstance(value, LegalIRInteropLossMode):
        return value
    try:
        return LegalIRInteropLossMode(str(value or ""))
    except ValueError:
        return LegalIRInteropLossMode.LOSSY


def _default_profile(fmt: LegalIRInteropFormat) -> str:
    return {
        LegalIRInteropFormat.DECOMPILER_JSON: "legal-ir-decompiler-json-v1",
        LegalIRInteropFormat.KG_JSON: "legal-ir-kg-json-v1",
        LegalIRInteropFormat.LEGAL_JSON: "legal-ir-canonical-json-v1",
        LegalIRInteropFormat.LEGAL_XML: "legal-ir-legal-xml-v1",
        LegalIRInteropFormat.PROOF_JSON: "legal-ir-proof-json-v1",
        LegalIRInteropFormat.RDF_OWL_JSONLD: "legal-ir-rdf-owl-jsonld-v1",
    }[fmt]


def _source_map(value: LegalIRSourceMap | Mapping[str, Any] | None) -> LegalIRSourceMap | None:
    if value is None:
        return None
    if isinstance(value, LegalIRSourceMap):
        return value
    data = _mapping(value)
    return LegalIRSourceMap.from_dict(data) if data else None


def _xml_namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _xml_name(name: str, namespace: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _xml_text(root: ET.Element, name: str, namespace: str) -> str:
    child = root.find(_xml_name(name, namespace))
    return "" if child is None or child.text is None else str(child.text)


def _json_child(element: ET.Element, name: str, namespace: str, default: Any) -> Any:
    child = element.find(_xml_name(name, namespace))
    if child is None or child.text is None or child.text == "":
        return default
    try:
        return json.loads(child.text)
    except json.JSONDecodeError:
        return child.text


def _camel_tag(value: str) -> str:
    return "".join(part.capitalize() for part in str(value).split("_"))


def _rdf_id(prefix: str, value: str) -> str:
    return f"lir:{prefix}/{_slug(value)}"


def _operator_from_statement(statement: str) -> str:
    lowered = statement.lower()
    for token in ("shall not", "must not", "shall", "must", "may"):
        if token in lowered:
            return token
    return "shall" if statement else ""


def _slug(value: Any) -> str:
    token = _token(value)
    return token or "unknown"


def _token(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().lower()
    return re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    return [_json_ready(value)]


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _sequence(value) if str(item)]


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _unique_text(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return {str(key): item for key, item in converted.items()}
    return {}


def _drop_empty(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in value.items()
        if not _empty(item) or key in {"document_id", "citation", "text", "schema_version"}
    }


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value == ()


def _dedupe_dicts(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for value in values:
        ready = _json_ready(value)
        digest = _stable_hash(ready)
        if digest in seen:
            continue
        seen.add(digest)
        output.append(ready)
    return output


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    return str(value)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "LEGAL_IR_INTEROP_MAPPING_SCHEMA_VERSION",
    "LEGAL_IR_INTEROP_ROUND_TRIP_SCHEMA_VERSION",
    "LEGAL_IR_INTEROP_SCHEMA_VERSION",
    "LEGAL_IR_RDF_CONTEXT",
    "LEGAL_IR_XML_NAMESPACE",
    "LegalIRInteropDirection",
    "LegalIRInteropEnvelope",
    "LegalIRInteropError",
    "LegalIRInteropFormat",
    "LegalIRInteropLossMarker",
    "LegalIRInteropLossMode",
    "LegalIRInteropRoundTripResult",
    "LegalIRInteropSchemaMapping",
    "assert_legal_ir_interop_round_trip_conformant",
    "export_legal_ir_interchange",
    "import_legal_ir_interchange",
    "read_legal_ir_interchange_json",
    "round_trip_legal_ir_interchange",
    "supported_legal_ir_projection",
    "write_legal_ir_interchange_json",
]
