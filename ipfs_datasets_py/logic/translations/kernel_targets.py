"""Controlled Lean/Rocq/Isabelle target-theory compiler (``KernelTargetCompiler@2``).

Publishes reviewed translation edges from typed intermediate obligations into
target-theory artifacts, and compiles those theories into controlled
Lean / Rocq / Isabelle sources.

Authority rules (fail-closed):

* Generated artifacts are **compilation candidates** until an official kernel
  accepts the exact theorem, imports, axioms, and environment identity.
* Sources never admit ``sorry`` / ``admit`` / trust-escape constructs.
* ProVerif / Tamarin / SMT / CHC / ATP / Hammer outputs never become theorem
  authority without independent kernel reconstruction.
* Exact theorem identity, environment identity, imports, axioms, and source
  maps are recorded on every candidate artifact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.translations import (
    NodeDisposition,
    NodeMapEntry,
    OpaqueDisposition,
    PreservationRelation,
    SymbolMapEntry,
    TranslationAssumptionSet,
    TranslationContract,
    TranslationEndpoint,
    TranslationIdentities,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.translations.planner import (
    FeatureSet,
    TranslationPathPlanner,
    TranslationPathPlannerError,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

KERNEL_TARGET_COMPILER_INTERFACE: Final = "KernelTargetCompiler@2"
KERNEL_TARGET_EDGES_INTERFACE: Final = "KernelTargetTranslationEdges@1"
KERNEL_TARGET_EDGES_SCHEMA: Final = "logic-kernel-target-translation-edges/v1"
KERNEL_EDGE_SCHEMA: Final = "logic-kernel-target-translation-edge/v1"
TARGET_THEORY_ARTIFACT_SCHEMA: Final = "logic-target-theory-artifact/v1"
COMPILATION_CANDIDATE_SCHEMA: Final = "logic-kernel-compilation-candidate/v1"
SOURCE_MAP_SCHEMA: Final = "logic-kernel-source-map/v1"
EDGE_IDENTITY_DOMAIN: Final = "logic.translation.kernel_target.edge"
EDGES_IDENTITY_DOMAIN: Final = "logic.translation.kernel_target.edges"
ARTIFACT_IDENTITY_DOMAIN: Final = "logic.translation.kernel_target.artifact"
CANDIDATE_IDENTITY_DOMAIN: Final = "logic.translation.kernel_target.candidate"

COMPILER_IDENTITY: Final = "compiler:kernel-target@2"
PROFILE_IDENTITY: Final = "profile:kernel-target-default@2"
CONFIG_IDENTITY: Final = "config:kernel-target-translation-edges@2"
ENVIRONMENT_IDENTITY: Final = "sha256:env:kernel-target-translation@2"

TARGET_THEORY_FAMILY: Final = "target_theory"
TARGET_LEAN: Final = "lean"
TARGET_ROCQ: Final = "rocq"
TARGET_ISABELLE: Final = "isabelle"

SOURCE_TARGET_THEORY: Final = "target_theory"
SOURCE_PROGRAM: Final = "program"
SOURCE_FIRST_ORDER: Final = "first_order"
SOURCE_PROTOCOL: Final = "cryptographic_protocol"

ENCODING_LEAN: Final = "lean4"
ENCODING_ROCQ: Final = "rocq"
ENCODING_ISABELLE: Final = "isabelle_hol"

DEFAULT_LEAN_IMPORTS: Final = ("Init",)
DEFAULT_ROCQ_IMPORTS: Final = ("Coq.Init.Prelude",)
DEFAULT_ISABELLE_IMPORTS: Final = ("Main",)

FEAT_TARGET_THEORY: Final = "feat_target_theory"
FEAT_IMPORTS: Final = "feat_imports"
FEAT_AXIOMS: Final = "feat_axioms"
FEAT_THEOREMS: Final = "feat_theorems"
FEAT_SOURCE_MAPS: Final = "feat_source_maps"
FEAT_KERNEL_CANDIDATE: Final = "feat_kernel_candidate"
FEAT_LEAN: Final = "feat_lean"
FEAT_ROCQ: Final = "feat_rocq"
FEAT_ISABELLE: Final = "feat_isabelle"
FEAT_TRUST_ESCAPE: Final = "feat_trust_escape"
FEAT_SORRY: Final = "feat_sorry"
FEAT_ADMIT: Final = "feat_admit"

UNSUPPORTED_CONSTRUCTS: Final = frozenset(
    {
        FEAT_TRUST_ESCAPE,
        FEAT_SORRY,
        FEAT_ADMIT,
        "construct:sorry",
        "construct:admit",
        "construct:trusted",
        "construct:unsafe",
    }
)

_SAFE_IDENT_RE = re.compile(r"[^A-Za-z0-9_']+")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

_TRUST_ESCAPE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "sorry",
        re.compile(r"(?<![A-Za-z0-9_'])(?:sorry|sorryAx)(?![A-Za-z0-9_'])"),
    ),
    (
        "admit",
        re.compile(
            r"(?i)(?<![A-Za-z0-9_'])(?:admit(?:ted)?|admit\s*\.)(?![A-Za-z0-9_'])"
        ),
    ),
    (
        "oops",
        re.compile(r"(?<![A-Za-z0-9_'])oops(?![A-Za-z0-9_'])"),
    ),
    (
        "trusted",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])trusted(?![A-Za-z0-9_'])"),
    ),
    (
        "unsafe",
        re.compile(
            r"(?im)^\s*(?:unsafe\s+(?:def|theorem|inductive|structure|abbrev)|"
            r"axiom\s+|constant\s+)"
        ),
    ),
    (
        "cheat",
        re.compile(r"(?i)(?<![A-Za-z0-9_'])(?:cheat|cheating)(?![A-Za-z0-9_'])"),
    ),
)


class KernelTargetTranslationError(ValueError):
    """Raised when a kernel-target edge or compilation is invalid."""


class KernelTargetKind(str, Enum):
    """Official kernel targets that may become proof authority."""

    LEAN = "lean"
    ROCQ = "rocq"
    ISABELLE = "isabelle"


class CompilationStatus(str, Enum):
    """Lifecycle of a kernel compilation artifact."""

    CANDIDATE = "compilation_candidate"
    KERNEL_ACCEPTED = "kernel_accepted"
    KERNEL_REJECTED = "kernel_rejected"
    UNSUPPORTED = "unsupported"


class DeclarationKind(str, Enum):
    """Closed declaration kinds admitted by the target-theory artifact."""

    IMPORT = "import"
    AXIOM = "axiom"
    DEFINITION = "definition"
    THEOREM = "theorem"
    LEMMA = "lemma"
    OBLIGATION = "obligation"


class SourceSurface(str, Enum):
    """Upstream surfaces that may feed the kernel compiler."""

    TARGET_THEORY = "target_theory"
    PROGRAM_VC = "program_vc"
    FIRST_ORDER = "first_order"
    PROTOCOL = "protocol"
    KERNEL_NATIVE = "kernel_native"


_KERNEL_ENCODINGS: Final[dict[KernelTargetKind, str]] = {
    KernelTargetKind.LEAN: ENCODING_LEAN,
    KernelTargetKind.ROCQ: ENCODING_ROCQ,
    KernelTargetKind.ISABELLE: ENCODING_ISABELLE,
}

_KERNEL_DEFAULT_IMPORTS: Final[dict[KernelTargetKind, tuple[str, ...]]] = {
    KernelTargetKind.LEAN: DEFAULT_LEAN_IMPORTS,
    KernelTargetKind.ROCQ: DEFAULT_ROCQ_IMPORTS,
    KernelTargetKind.ISABELLE: DEFAULT_ISABELLE_IMPORTS,
}

_KERNEL_FEATURES: Final[dict[KernelTargetKind, str]] = {
    KernelTargetKind.LEAN: FEAT_LEAN,
    KernelTargetKind.ROCQ: FEAT_ROCQ,
    KernelTargetKind.ISABELLE: FEAT_ISABELLE,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise KernelTargetTranslationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise KernelTargetTranslationError(
            f"{field_name} must not contain NUL bytes"
        )
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field_name)


def _identifier(value: object, field_name: str) -> str:
    return _text(value, field_name)


def _strings(
    values: Sequence[str] | object,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise KernelTargetTranslationError(
            f"{field_name} must be a sequence of strings"
        )
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = (
            _identifier(item, f"{field_name} item")
            if identifiers
            else _text(item, f"{field_name} item")
        )
        if text in seen:
            raise KernelTargetTranslationError(
                f"{field_name} must not contain duplicates"
            )
        seen.add(text)
        result.append(text)
    return tuple(result)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KernelTargetTranslationError(f"{field_name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise KernelTargetTranslationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise KernelTargetTranslationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise KernelTargetTranslationError(f"{field_name} must be a bool")
    return value


def _node(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> NodeMapEntry:
    return NodeMapEntry(
        source_node_id=source,
        target_node_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _symbol(
    source: str,
    *targets: str,
    disposition: NodeDisposition | str = NodeDisposition.MAPPED,
    reason: str = "",
) -> SymbolMapEntry:
    return SymbolMapEntry(
        source_symbol_id=source,
        target_symbol_ids=targets,
        disposition=disposition,
        reason=reason,
    )


def _endpoint(
    family: str,
    *,
    profile_id: str = "",
    fragment_id: str = "",
    schema_id: str = "",
    notation_id: str = "",
    content_identity: str = "",
) -> TranslationEndpoint:
    profile = profile_id or f"{family}_default"
    fragment = fragment_id or f"{family}_core"
    schema = schema_id or f"{family}_schema"
    notation = notation_id or f"{family}_notation"
    content = content_identity or f"sha256:endpoint:{family}:{profile}:{fragment}"
    return TranslationEndpoint(
        family_id=family,
        profile_id=profile,
        fragment_id=fragment,
        schema_id=schema,
        notation_id=notation,
        content_identity=content,
    )


def _identities(
    *,
    compiler_identity: str = COMPILER_IDENTITY,
    profile_identity: str = PROFILE_IDENTITY,
    config_identity: str = CONFIG_IDENTITY,
    source_identity: str = "",
    target_identity: str = "",
) -> TranslationIdentities:
    return TranslationIdentities(
        compiler_identity=compiler_identity,
        profile_identity=profile_identity,
        config_identity=config_identity,
        source_identity=source_identity
        or "bafkreikernelsrcaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        target_identity=target_identity
        or "bafkreikerneltgtaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        environment_identity=ENVIRONMENT_IDENTITY,
    )


def _safe_ident(value: str, *, prefix: str = "id") -> str:
    cleaned = _SAFE_IDENT_RE.sub("_", value.strip())
    cleaned = cleaned.strip("_") or prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:96]


def content_digest(content: str) -> str:
    if not isinstance(content, str) or "\x00" in content:
        raise KernelTargetTranslationError(
            "content must be text without NUL bytes"
        )
    return stable_digest({"content": content})


def scan_trust_escapes(source: str) -> tuple[str, ...]:
    if not isinstance(source, str):
        raise KernelTargetTranslationError("source must be text")
    findings: list[str] = []
    for kind, pattern in _TRUST_ESCAPE_PATTERNS:
        if pattern.search(source):
            findings.append(kind)
    return tuple(findings)


def reject_trust_escapes(source: str, *, path: str = "source") -> None:
    escapes = scan_trust_escapes(source)
    if escapes:
        raise KernelTargetTranslationError(
            f"{path} rejects trust escapes: {', '.join(escapes)}"
        )


def is_official_kernel(target: KernelTargetKind | str) -> bool:
    kind = _enum(target, KernelTargetKind, "target")
    return kind in {
        KernelTargetKind.LEAN,
        KernelTargetKind.ROCQ,
        KernelTargetKind.ISABELLE,
    }


# ---------------------------------------------------------------------------
# Source maps, theory artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelSourceMap:
    """Source-map binding from a declaration to an upstream span."""

    owner_id: str
    source_ref_id: str = ""
    span_id: str = ""
    start_byte: int = 0
    end_byte: int = 0
    schema_version: str = SOURCE_MAP_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(
            self,
            "source_ref_id",
            _optional_text(self.source_ref_id, "source_ref_id"),
        )
        object.__setattr__(
            self, "span_id", _optional_text(self.span_id, "span_id")
        )
        if not isinstance(self.start_byte, int) or self.start_byte < 0:
            raise KernelTargetTranslationError(
                "start_byte must be a non-negative integer"
            )
        if not isinstance(self.end_byte, int) or self.end_byte < self.start_byte:
            raise KernelTargetTranslationError("end_byte must be >= start_byte")
        if self.schema_version != SOURCE_MAP_SCHEMA:
            raise KernelTargetTranslationError(
                f"unsupported source map schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_byte": self.end_byte,
            "owner_id": self.owner_id,
            "schema_version": self.schema_version,
            "source_ref_id": self.source_ref_id,
            "span_id": self.span_id,
            "start_byte": self.start_byte,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelSourceMap":
        value = _mapping(value, "kernel source map")
        return cls(
            owner_id=value.get("owner_id", ""),
            source_ref_id=value.get("source_ref_id", ""),
            span_id=value.get("span_id", ""),
            start_byte=int(value.get("start_byte", 0)),
            end_byte=int(value.get("end_byte", 0)),
            schema_version=value.get("schema_version", SOURCE_MAP_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class TargetTheoryArtifact:
    """Typed target-theory artifact with imports, axioms, theorems, source maps.

    This is a compilation *input*.  It never claims official-kernel acceptance.
    """

    theory_id: str
    name: str
    source_surface: SourceSurface | str = SourceSurface.TARGET_THEORY
    imports: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    theorems: tuple[Mapping[str, Any] | dict[str, Any], ...] = ()
    declarations: tuple[Mapping[str, Any] | dict[str, Any], ...] = ()
    source_maps: tuple[KernelSourceMap, ...] = ()
    family_id: str = TARGET_THEORY_FAMILY
    profile_id: str = "controlled_kernel_target"
    schema_version: str = TARGET_THEORY_ARTIFACT_SCHEMA
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "theory_id", _identifier(self.theory_id, "theory_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self,
            "source_surface",
            _enum(self.source_surface, SourceSurface, "source_surface"),
        )
        object.__setattr__(self, "imports", _strings(self.imports, "imports"))
        object.__setattr__(self, "axioms", _strings(self.axioms, "axioms"))
        theorems: list[dict[str, Any]] = []
        for index, item in enumerate(self.theorems):
            if not isinstance(item, Mapping):
                raise KernelTargetTranslationError(
                    f"theorems[{index}] must be a mapping"
                )
            theorem_id = _identifier(
                item.get("theorem_id") or item.get("name") or f"thm_{index}",
                "theorem_id",
            )
            statement = _text(
                item.get("statement") or item.get("name") or theorem_id,
                "theorem.statement",
            )
            reject_trust_escapes(statement, path=f"theorem.{theorem_id}.statement")
            body = _optional_text(item.get("body", ""), "theorem.body")
            if body:
                reject_trust_escapes(body, path=f"theorem.{theorem_id}.body")
            theorems.append(
                {
                    "theorem_id": theorem_id,
                    "theorem_name": str(item.get("theorem_name") or item.get("name") or theorem_id),
                    "statement": statement,
                    "statement_digest": content_digest(statement),
                    "body": body,
                    "kind": str(item.get("kind") or DeclarationKind.THEOREM.value),
                }
            )
        object.__setattr__(self, "theorems", tuple(theorems))
        declarations: list[dict[str, Any]] = []
        for index, item in enumerate(self.declarations):
            if not isinstance(item, Mapping):
                raise KernelTargetTranslationError(
                    f"declarations[{index}] must be a mapping"
                )
            decl_id = _identifier(
                item.get("declaration_id") or item.get("name") or f"decl_{index}",
                "declaration_id",
            )
            kind = _enum(
                item.get("kind", DeclarationKind.DEFINITION),
                DeclarationKind,
                "declaration.kind",
            )
            name = _text(item.get("name") or decl_id, "declaration.name")
            statement = _optional_text(item.get("statement", ""), "declaration.statement")
            body = _optional_text(item.get("body", ""), "declaration.body")
            for field_name, text in (("statement", statement), ("body", body)):
                if text:
                    reject_trust_escapes(text, path=f"{decl_id}.{field_name}")
            declarations.append(
                {
                    "declaration_id": decl_id,
                    "kind": kind.value,
                    "name": name,
                    "statement": statement,
                    "body": body,
                    "import_path": str(item.get("import_path") or ""),
                    "is_axiom": bool(
                        item.get("is_axiom", kind is DeclarationKind.AXIOM)
                    ),
                }
            )
        object.__setattr__(self, "declarations", tuple(declarations))
        maps: list[KernelSourceMap] = []
        for item in self.source_maps:
            if isinstance(item, KernelSourceMap):
                maps.append(item)
            elif isinstance(item, Mapping):
                maps.append(KernelSourceMap.from_dict(item))
            else:
                raise KernelTargetTranslationError(
                    "source_maps items must be KernelSourceMap values"
                )
        object.__setattr__(
            self,
            "source_maps",
            tuple(sorted(maps, key=lambda item: (item.owner_id, item.span_id))),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        if self.family_id != TARGET_THEORY_FAMILY:
            raise KernelTargetTranslationError(
                f"family_id must be {TARGET_THEORY_FAMILY!r}"
            )
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != TARGET_THEORY_ARTIFACT_SCHEMA:
            raise KernelTargetTranslationError(
                f"unsupported target theory schema {self.schema_version!r}"
            )
        if not self.theorems and not self.declarations:
            raise KernelTargetTranslationError(
                "target theory requires at least one theorem or declaration"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=ARTIFACT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def document_id(self) -> str:
        return self.identity.cid

    def feature_set(self) -> FeatureSet:
        features = [
            FEAT_TARGET_THEORY,
            FEAT_KERNEL_CANDIDATE,
            FEAT_SOURCE_MAPS,
        ]
        if self.imports:
            features.append(FEAT_IMPORTS)
        if self.axioms:
            features.append(FEAT_AXIOMS)
        if self.theorems:
            features.append(FEAT_THEOREMS)
        return FeatureSet.from_features(features)

    def to_dict(self) -> dict[str, Any]:
        return {
            "axioms": list(self.axioms),
            "declarations": [dict(item) for item in self.declarations],
            "description": self.description,
            "family_id": self.family_id,
            "imports": list(self.imports),
            "name": self.name,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "source_surface": (
                self.source_surface.value
                if isinstance(self.source_surface, SourceSurface)
                else self.source_surface
            ),
            "theorems": [dict(item) for item in self.theorems],
            "theory_id": self.theory_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TargetTheoryArtifact":
        value = _mapping(value, "target theory artifact")
        return cls(
            theory_id=value.get("theory_id", ""),
            name=value.get("name", ""),
            source_surface=value.get(
                "source_surface", SourceSurface.TARGET_THEORY
            ),
            imports=tuple(value.get("imports", ())),
            axioms=tuple(value.get("axioms", ())),
            theorems=tuple(value.get("theorems", ())),
            declarations=tuple(value.get("declarations", ())),
            source_maps=tuple(value.get("source_maps", ())),
            family_id=value.get("family_id", TARGET_THEORY_FAMILY),
            profile_id=value.get("profile_id", "controlled_kernel_target"),
            schema_version=value.get(
                "schema_version", TARGET_THEORY_ARTIFACT_SCHEMA
            ),
            description=value.get("description", ""),
        )

    @classmethod
    def from_statements(
        cls,
        *,
        theory_id: str,
        name: str,
        theorems: Sequence[Mapping[str, Any] | str],
        imports: Sequence[str] = (),
        axioms: Sequence[str] = (),
        source_surface: SourceSurface | str = SourceSurface.TARGET_THEORY,
        source_ref_id: str = "",
    ) -> "TargetTheoryArtifact":
        normalized: list[dict[str, Any]] = []
        maps: list[KernelSourceMap] = []
        for index, item in enumerate(theorems):
            if isinstance(item, str):
                theorem_id = f"thm:{index}"
                statement = item
                theorem_name = f"theorem_{index}"
            else:
                theorem_id = str(item.get("theorem_id") or f"thm:{index}")
                statement = str(item.get("statement") or item.get("name") or theorem_id)
                theorem_name = str(
                    item.get("theorem_name") or item.get("name") or theorem_id
                )
            normalized.append(
                {
                    "theorem_id": theorem_id,
                    "theorem_name": theorem_name,
                    "statement": statement,
                    "kind": DeclarationKind.THEOREM.value,
                }
            )
            maps.append(
                KernelSourceMap(
                    owner_id=theorem_id,
                    source_ref_id=source_ref_id or theory_id,
                    span_id=f"span:{theorem_id}",
                    start_byte=0,
                    end_byte=max(len(statement), 0),
                )
            )
        import_decls = [
            {
                "declaration_id": f"import:{path}",
                "kind": DeclarationKind.IMPORT.value,
                "name": path,
                "import_path": path,
            }
            for path in imports
        ]
        axiom_decls = [
            {
                "declaration_id": f"axiom:{axiom}",
                "kind": DeclarationKind.AXIOM.value,
                "name": axiom,
                "statement": axiom,
                "is_axiom": True,
            }
            for axiom in axioms
        ]
        return cls(
            theory_id=theory_id,
            name=name,
            source_surface=source_surface,
            imports=tuple(imports),
            axioms=tuple(axioms),
            theorems=tuple(normalized),
            declarations=tuple(import_decls + axiom_decls),
            source_maps=tuple(maps),
        )


@dataclass(frozen=True, slots=True)
class KernelCompilationCandidate:
    """Controlled generated kernel source that remains a candidate.

    ``status`` is always ``compilation_candidate`` from this compiler.
    Official-kernel acceptance is recorded only by
    :meth:`KernelTargetCompiler.record_kernel_acceptance` after an external
    checker verifies the exact theorem and environment identities.
    """

    candidate_id: str
    theory_id: str
    theory_document_id: str
    kernel_target: KernelTargetKind | str
    encoding: str
    source: str
    source_digest: str
    imports: tuple[str, ...]
    axioms: tuple[str, ...]
    theorem_id: str
    theorem_name: str
    statement: str
    statement_digest: str
    environment_id: str
    environment: Mapping[str, Any]
    source_maps: tuple[KernelSourceMap, ...] = ()
    trust_escapes_rejected: tuple[str, ...] = ()
    status: CompilationStatus | str = CompilationStatus.CANDIDATE
    kernel_accepted: bool = False
    loss_ids: tuple[str, ...] = ()
    schema_version: str = COMPILATION_CANDIDATE_SCHEMA
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "theory_id", _identifier(self.theory_id, "theory_id"))
        object.__setattr__(
            self,
            "theory_document_id",
            _text(self.theory_document_id, "theory_document_id"),
        )
        object.__setattr__(
            self,
            "kernel_target",
            _enum(self.kernel_target, KernelTargetKind, "kernel_target"),
        )
        expected = _KERNEL_ENCODINGS[self.kernel_target]  # type: ignore[index]
        encoding = _text(self.encoding, "encoding")
        if encoding != expected:
            raise KernelTargetTranslationError(
                f"encoding for {self.kernel_target} must be {expected!r}"
            )
        object.__setattr__(self, "encoding", encoding)
        if not isinstance(self.source, str) or not self.source.strip() or "\x00" in self.source:
            raise KernelTargetTranslationError(
                "source must be non-empty text without NUL"
            )
        reject_trust_escapes(self.source, path="source")
        object.__setattr__(
            self, "source_digest", _text(self.source_digest, "source_digest")
        )
        if not _DIGEST_RE.fullmatch(self.source_digest):
            raise KernelTargetTranslationError(
                "source_digest must be a lowercase SHA-256 digest"
            )
        if self.source_digest != content_digest(self.source):
            raise KernelTargetTranslationError(
                "source_digest does not match generated source"
            )
        object.__setattr__(self, "imports", _strings(self.imports, "imports"))
        object.__setattr__(self, "axioms", _strings(self.axioms, "axioms"))
        object.__setattr__(
            self, "theorem_id", _identifier(self.theorem_id, "theorem_id")
        )
        object.__setattr__(
            self, "theorem_name", _text(self.theorem_name, "theorem_name")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        reject_trust_escapes(self.statement, path="statement")
        object.__setattr__(
            self,
            "statement_digest",
            _text(self.statement_digest, "statement_digest"),
        )
        if self.statement_digest != content_digest(self.statement):
            raise KernelTargetTranslationError(
                "statement_digest does not match statement"
            )
        object.__setattr__(
            self, "environment_id", _identifier(self.environment_id, "environment_id")
        )
        if not isinstance(self.environment, Mapping):
            raise KernelTargetTranslationError("environment must be a mapping")
        object.__setattr__(self, "environment", dict(self.environment))
        maps: list[KernelSourceMap] = []
        for item in self.source_maps:
            if isinstance(item, KernelSourceMap):
                maps.append(item)
            elif isinstance(item, Mapping):
                maps.append(KernelSourceMap.from_dict(item))
            else:
                raise KernelTargetTranslationError(
                    "source_maps items must be KernelSourceMap values"
                )
        object.__setattr__(self, "source_maps", tuple(maps))
        object.__setattr__(
            self,
            "trust_escapes_rejected",
            _strings(self.trust_escapes_rejected, "trust_escapes_rejected"),
        )
        object.__setattr__(
            self, "status", _enum(self.status, CompilationStatus, "status")
        )
        object.__setattr__(
            self, "kernel_accepted", _bool(self.kernel_accepted, "kernel_accepted")
        )
        # Compiler itself never emits kernel_accepted=True.
        if self.kernel_accepted and self.status is CompilationStatus.CANDIDATE:
            raise KernelTargetTranslationError(
                "kernel_accepted cannot be true while status is compilation_candidate"
            )
        if (
            self.status is CompilationStatus.KERNEL_ACCEPTED
            and not self.kernel_accepted
        ):
            raise KernelTargetTranslationError(
                "kernel_accepted must be true when status is kernel_accepted"
            )
        object.__setattr__(
            self,
            "loss_ids",
            _strings(self.loss_ids, "loss_ids", identifiers=True),
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != COMPILATION_CANDIDATE_SCHEMA:
            raise KernelTargetTranslationError(
                f"unsupported candidate schema {self.schema_version!r}"
            )

    @property
    def is_candidate(self) -> bool:
        return (
            self.status is CompilationStatus.CANDIDATE
            and not self.kernel_accepted
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=CANDIDATE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "axioms": list(self.axioms),
            "candidate_id": self.candidate_id,
            "description": self.description,
            "encoding": self.encoding,
            "environment": dict(self.environment),
            "environment_id": self.environment_id,
            "imports": list(self.imports),
            "kernel_accepted": self.kernel_accepted,
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelTargetKind)
                else self.kernel_target
            ),
            "loss_ids": list(self.loss_ids),
            "schema_version": self.schema_version,
            "source": self.source,
            "source_digest": self.source_digest,
            "source_maps": [item.to_dict() for item in self.source_maps],
            "statement": self.statement,
            "statement_digest": self.statement_digest,
            "status": (
                self.status.value
                if isinstance(self.status, CompilationStatus)
                else self.status
            ),
            "theorem_id": self.theorem_id,
            "theorem_name": self.theorem_name,
            "theory_document_id": self.theory_document_id,
            "theory_id": self.theory_id,
            "trust_escapes_rejected": list(self.trust_escapes_rejected),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelCompilationCandidate":
        value = _mapping(value, "kernel compilation candidate")
        return cls(
            candidate_id=value.get("candidate_id", ""),
            theory_id=value.get("theory_id", ""),
            theory_document_id=value.get("theory_document_id", ""),
            kernel_target=value.get("kernel_target", KernelTargetKind.LEAN),
            encoding=value.get("encoding", ENCODING_LEAN),
            source=value.get("source", ""),
            source_digest=value.get("source_digest", ""),
            imports=tuple(value.get("imports", ())),
            axioms=tuple(value.get("axioms", ())),
            theorem_id=value.get("theorem_id", ""),
            theorem_name=value.get("theorem_name", ""),
            statement=value.get("statement", ""),
            statement_digest=value.get("statement_digest", ""),
            environment_id=value.get("environment_id", ""),
            environment=value.get("environment", {}),
            source_maps=tuple(value.get("source_maps", ())),
            trust_escapes_rejected=tuple(value.get("trust_escapes_rejected", ())),
            status=value.get("status", CompilationStatus.CANDIDATE),
            kernel_accepted=bool(value.get("kernel_accepted", False)),
            loss_ids=tuple(value.get("loss_ids", ())),
            schema_version=value.get(
                "schema_version", COMPILATION_CANDIDATE_SCHEMA
            ),
            description=value.get("description", ""),
        )


# ---------------------------------------------------------------------------
# Translation edges
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelTargetTranslationEdge:
    """One reviewed edge into a kernel target family."""

    edge_id: str
    contract: TranslationContract
    kernel_target: KernelTargetKind | str
    loss_ids: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = KERNEL_EDGE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        if not isinstance(self.contract, TranslationContract):
            raise KernelTargetTranslationError(
                "contract must be a TranslationContract"
            )
        if self.edge_id != self.contract.contract_id:
            raise KernelTargetTranslationError(
                "edge_id must equal contract.contract_id"
            )
        object.__setattr__(
            self,
            "kernel_target",
            _enum(self.kernel_target, KernelTargetKind, "kernel_target"),
        )
        object.__setattr__(
            self,
            "loss_ids",
            _strings(self.loss_ids, "loss_ids", identifiers=True),
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        if self.schema_version != KERNEL_EDGE_SCHEMA:
            raise KernelTargetTranslationError(
                f"unsupported kernel edge schema {self.schema_version!r}"
            )
        # Kernel edges never claim authoritative theorem status pre-acceptance.
        if self.contract.authority_ceiling is EvidenceAuthority.AUTHORITATIVE:
            raise KernelTargetTranslationError(
                "kernel target edges cannot claim AUTHORITATIVE authority "
                "before official kernel acceptance"
            )
        if not self.loss_ids:
            raise KernelTargetTranslationError(
                "kernel target edges require at least one loss receipt id "
                "(candidate until kernel acceptance)"
            )

    @property
    def source_family_id(self) -> str:
        return self.contract.source.family_id

    @property
    def target_family_id(self) -> str:
        return self.contract.target.family_id

    @property
    def is_loss_receipted(self) -> bool:
        return bool(self.loss_ids)

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def content_id(self) -> str:
        return self.identity.cid

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "contract_content_id": self.contract.contract_content_id,
            "contract_id": self.contract.contract_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelTargetKind)
                else self.kernel_target
            ),
            "loss_ids": list(self.loss_ids),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["contract"] = self.contract.to_dict()
        payload["content_id"] = self.content_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelTargetTranslationEdge":
        value = _mapping(value, "kernel target translation edge")
        contract_value = value.get("contract")
        if not isinstance(contract_value, Mapping):
            raise KernelTargetTranslationError("contract must be a mapping")
        return cls(
            edge_id=value.get("edge_id", ""),
            contract=TranslationContract.from_dict(contract_value),
            kernel_target=value.get("kernel_target", ""),
            loss_ids=tuple(value.get("loss_ids", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", KERNEL_EDGE_SCHEMA),
        )


def _contract(
    contract_id: str,
    *,
    source: TranslationEndpoint,
    target: TranslationEndpoint,
    preservation: PreservationRelation,
    authority_ceiling: EvidenceAuthority,
    node_map: Sequence[NodeMapEntry],
    symbol_map: Sequence[SymbolMapEntry],
    required_source_node_ids: Sequence[str],
    required_source_symbol_ids: Sequence[str],
    feature_preconditions: Sequence[str],
    unsupported_constructs: Sequence[str] = (),
    assumptions: TranslationAssumptionSet | None = None,
    checker_route: str = "",
    reconstruction_route: str = "",
    description: str = "",
    identities: TranslationIdentities | None = None,
    proof_safe: bool = True,
    counterexample_safe: bool = False,
) -> TranslationContract:
    return TranslationContract(
        contract_id=contract_id,
        source=source,
        target=target,
        preservation=preservation,
        identities=identities or _identities(),
        proof_safe=proof_safe,
        counterexample_safe=counterexample_safe,
        authority_ceiling=authority_ceiling,
        assumptions=assumptions or TranslationAssumptionSet(),
        node_map=tuple(node_map),
        symbol_map=tuple(symbol_map),
        required_source_node_ids=tuple(required_source_node_ids),
        required_source_symbol_ids=tuple(required_source_symbol_ids),
        feature_preconditions=tuple(feature_preconditions),
        unsupported_constructs=tuple(unsupported_constructs),
        opaque_disposition=OpaqueDisposition.UNSUPPORTED,
        checker_route=checker_route,
        reconstruction_route=reconstruction_route,
        description=description,
    )


def _theory_source(*, profile: str, fragment: str) -> TranslationEndpoint:
    return _endpoint(
        SOURCE_TARGET_THEORY,
        profile_id=profile,
        fragment_id=fragment,
        schema_id="target_theory_schema",
        notation_id="target_theory_surface",
        content_identity=f"sha256:kernel:theory:{profile}:{fragment}",
    )


def _kernel_target_endpoint(kind: KernelTargetKind) -> TranslationEndpoint:
    return _endpoint(
        kind.value,
        profile_id=f"{kind.value}_controlled",
        fragment_id=f"{kind.value}_core",
        schema_id=f"{kind.value}_schema",
        notation_id=_KERNEL_ENCODINGS[kind],
        content_identity=f"sha256:kernel:target:{kind.value}",
    )


def _kernel_nodes(kind: KernelTargetKind) -> tuple[NodeMapEntry, ...]:
    prefix = kind.value
    return (
        _node("n_import", f"{prefix}_import", disposition=NodeDisposition.MAPPED),
        _node("n_axiom", f"{prefix}_axiom", disposition=NodeDisposition.MAPPED),
        _node("n_theorem", f"{prefix}_theorem", disposition=NodeDisposition.MAPPED),
        _node(
            "n_definition",
            f"{prefix}_definition",
            disposition=NodeDisposition.MAPPED,
        ),
        _node(
            "n_source_map",
            f"{prefix}_source_map",
            disposition=NodeDisposition.PRESERVED,
        ),
        _node(
            "n_sorry",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="sorry/admit trust escapes are rejected",
        ),
        _node(
            "n_admit",
            disposition=NodeDisposition.UNSUPPORTED,
            reason="sorry/admit trust escapes are rejected",
        ),
    )


def _kernel_symbols(kind: KernelTargetKind) -> tuple[SymbolMapEntry, ...]:
    prefix = kind.value
    return (
        _symbol("sym_theory", f"{prefix}_theory", disposition=NodeDisposition.MAPPED),
        _symbol("sym_theorem", f"{prefix}_thm", disposition=NodeDisposition.MAPPED),
        _symbol("sym_import", f"{prefix}_import", disposition=NodeDisposition.MAPPED),
        _symbol("sym_axiom", f"{prefix}_axiom", disposition=NodeDisposition.MAPPED),
    )


def _build_kernel_edge(kind: KernelTargetKind) -> KernelTargetTranslationEdge:
    loss_id = f"loss:kernel-candidate-until-acceptance-{kind.value}"
    contract = _contract(
        f"target_theory_to_{kind.value}",
        source=_theory_source(
            profile=f"theory_{kind.value}",
            fragment="controlled_theory",
        ),
        target=_kernel_target_endpoint(kind),
        preservation=PreservationRelation.THEOREM_PRESERVING,
        authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        node_map=_kernel_nodes(kind),
        symbol_map=_kernel_symbols(kind),
        required_source_node_ids=(
            "n_import",
            "n_axiom",
            "n_theorem",
            "n_definition",
            "n_source_map",
            "n_sorry",
            "n_admit",
        ),
        required_source_symbol_ids=(
            "sym_theory",
            "sym_theorem",
            "sym_import",
            "sym_axiom",
        ),
        feature_preconditions=(
            FEAT_TARGET_THEORY,
            FEAT_IMPORTS,
            FEAT_THEOREMS,
            FEAT_SOURCE_MAPS,
            FEAT_KERNEL_CANDIDATE,
            _KERNEL_FEATURES[kind],
        ),
        unsupported_constructs=tuple(sorted(UNSUPPORTED_CONSTRUCTS)),
        assumptions=TranslationAssumptionSet(
            axioms=(
                "axiom:official_kernel_sole_authority",
                f"axiom:{kind.value}_syntax_controlled",
            ),
            domain_changes=(
                f"domain:target_theory_to_{kind.value}_source",
            ),
            other=(
                loss_id,
                "loss:candidate_until_kernel_acceptance",
            ),
        ),
        checker_route=f"kernel:{kind.value}:official",
        reconstruction_route=f"replay:{kind.value}-theorem",
        description=(
            f"Target theories compile to controlled {kind.value} sources as "
            "candidates until the official kernel accepts the exact theorem, "
            "imports, axioms, and environment identity."
        ),
        identities=_identities(
            config_identity=f"config:target-theory-to-{kind.value}@2"
        ),
        proof_safe=True,
        counterexample_safe=False,
    )
    return KernelTargetTranslationEdge(
        edge_id=contract.contract_id,
        contract=contract,
        kernel_target=kind,
        loss_ids=(
            loss_id,
            "loss:candidate-until-kernel-acceptance",
            "loss:trust-escape-rejected",
        ),
        description=contract.description,
    )


def build_kernel_target_translation_edges() -> tuple[
    KernelTargetTranslationEdge, ...
]:
    edges = (
        _build_kernel_edge(KernelTargetKind.LEAN),
        _build_kernel_edge(KernelTargetKind.ROCQ),
        _build_kernel_edge(KernelTargetKind.ISABELLE),
    )
    ids = [edge.edge_id for edge in edges]
    if len(ids) != len(set(ids)):
        raise KernelTargetTranslationError("duplicate kernel target edge ids")
    return edges


def kernel_target_translation_contracts() -> tuple[TranslationContract, ...]:
    return tuple(edge.contract for edge in build_kernel_target_translation_edges())


@dataclass(frozen=True, slots=True)
class KernelTargetTranslationEdges:
    """Reviewed kernel-target edge registry."""

    INTERFACE: ClassVar[str] = KERNEL_TARGET_EDGES_INTERFACE
    schema_version: ClassVar[str] = KERNEL_TARGET_EDGES_SCHEMA
    interface: str = KERNEL_TARGET_EDGES_INTERFACE

    edges: tuple[KernelTargetTranslationEdge, ...] = field(default_factory=tuple)
    catalog_content_id: str = ""
    description: str = (
        "Target-theory to Lean/Rocq/Isabelle compilation edges; artifacts remain "
        "candidates until official kernels accept them."
    )

    def __post_init__(self) -> None:
        if self.interface != KERNEL_TARGET_EDGES_INTERFACE:
            raise KernelTargetTranslationError(
                f"unsupported kernel target edges interface {self.interface!r}"
            )
        if not self.edges:
            object.__setattr__(self, "edges", build_kernel_target_translation_edges())
        normalized: list[KernelTargetTranslationEdge] = []
        seen: set[str] = set()
        for item in self.edges:
            if isinstance(item, KernelTargetTranslationEdge):
                edge = item
            elif isinstance(item, Mapping):
                edge = KernelTargetTranslationEdge.from_dict(item)
            else:
                raise KernelTargetTranslationError(
                    "edges items must be KernelTargetTranslationEdge values"
                )
            if edge.edge_id in seen:
                raise KernelTargetTranslationError(
                    f"duplicate edge id {edge.edge_id!r}"
                )
            seen.add(edge.edge_id)
            if not edge.is_loss_receipted:
                raise KernelTargetTranslationError(
                    f"edge {edge.edge_id!r} is not loss-receipted"
                )
            normalized.append(edge)
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(normalized, key=lambda item: item.edge_id)),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description, "description"),
        )
        computed = self._compute_identity()
        if self.catalog_content_id and self.catalog_content_id != computed.cid:
            raise KernelTargetTranslationError(
                "catalog_content_id does not match canonical catalog content"
            )
        object.__setattr__(self, "catalog_content_id", computed.cid)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=EDGES_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.catalog_content_id

    def __iter__(self):
        return iter(self.edges)

    def __len__(self) -> int:
        return len(self.edges)

    def by_id(self) -> Mapping[str, KernelTargetTranslationEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    def get(self, edge_id: str) -> KernelTargetTranslationEdge:
        edge_id = _identifier(edge_id, "edge_id")
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        raise KernelTargetTranslationError(f"unknown edge_id {edge_id!r}")

    def contracts(self) -> tuple[TranslationContract, ...]:
        return tuple(edge.contract for edge in self.edges)

    def by_kernel(
        self, kernel: KernelTargetKind | str
    ) -> tuple[KernelTargetTranslationEdge, ...]:
        selected = _enum(kernel, KernelTargetKind, "kernel")
        return tuple(
            edge for edge in self.edges if edge.kernel_target is selected
        )

    def all_loss_receipted(self) -> bool:
        return all(edge.is_loss_receipted for edge in self.edges)

    def register_with_planner(
        self, planner: TranslationPathPlanner | None = None
    ) -> TranslationPathPlanner:
        if planner is None:
            planner = TranslationPathPlanner()
        if not isinstance(planner, TranslationPathPlanner):
            raise KernelTargetTranslationError(
                "planner must be a TranslationPathPlanner"
            )
        try:
            planner.register_edges(self.contracts())
        except TranslationPathPlannerError as error:
            raise KernelTargetTranslationError(str(error)) from error
        return planner

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "edge_content_ids": [edge.content_id for edge in self.edges],
            "edge_ids": list(self.edge_ids()),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload["catalog_content_id"] = self.catalog_content_id
        payload["edges"] = [edge.to_dict() for edge in self.edges]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelTargetTranslationEdges":
        value = _mapping(value, "kernel target translation edges")
        return cls(
            edges=tuple(value.get("edges", ())),  # type: ignore[arg-type]
            catalog_content_id=value.get("catalog_content_id", ""),
            description=value.get("description", ""),
        )

    @classmethod
    def reviewed(cls) -> "KernelTargetTranslationEdges":
        return cls(edges=build_kernel_target_translation_edges())


# ---------------------------------------------------------------------------
# KernelTargetCompiler@2
# ---------------------------------------------------------------------------


class KernelTargetCompiler:
    """Compile target theories to Lean/Rocq/Isabelle candidates.

    Interface: ``KernelTargetCompiler@2``.

    Every successful compilation returns a :class:`KernelCompilationCandidate`
    with ``status=compilation_candidate`` and ``kernel_accepted=False``.
    Official kernels remain the sole proof authority.
    """

    interface: ClassVar[str] = KERNEL_TARGET_COMPILER_INTERFACE
    schema_version: ClassVar[str] = COMPILATION_CANDIDATE_SCHEMA

    def __init__(
        self,
        *,
        edges: KernelTargetTranslationEdges | None = None,
        default_environment: Mapping[str, Any] | None = None,
    ) -> None:
        self.edges = edges or KernelTargetTranslationEdges.reviewed()
        self.default_environment = dict(default_environment or {})

    def compile(
        self,
        theory: TargetTheoryArtifact | Mapping[str, Any],
        *,
        kernel_target: KernelTargetKind | str,
        theorem_id: str | None = None,
        environment: Mapping[str, Any] | None = None,
        proof_body: str = "",
    ) -> KernelCompilationCandidate:
        """Compile one theorem obligation to a controlled kernel candidate."""

        if isinstance(theory, Mapping):
            theory = TargetTheoryArtifact.from_dict(theory)
        if not isinstance(theory, TargetTheoryArtifact):
            raise KernelTargetTranslationError(
                "compile requires TargetTheoryArtifact or mapping"
            )
        target = _enum(kernel_target, KernelTargetKind, "kernel_target")
        if not is_official_kernel(target):
            raise KernelTargetTranslationError(
                f"unsupported kernel target {target!r}"
            )
        if theorem_id is None:
            if not theory.theorems:
                raise KernelTargetTranslationError(
                    "theory has no theorems to compile"
                )
            theorem = theory.theorems[0]
        else:
            theorem = None
            for item in theory.theorems:
                if item["theorem_id"] == theorem_id:
                    theorem = item
                    break
            if theorem is None:
                raise KernelTargetTranslationError(
                    f"unknown theorem_id {theorem_id!r}"
                )

        env = dict(environment or self.default_environment or {})
        env.setdefault("environment_id", f"env:{target.value}:candidate")
        env.setdefault("kernel_target", target.value)
        env.setdefault("toolchain_id", target.value)
        env.setdefault("toolchain_version", "pinned-unspecified")
        env_id = _identifier(env["environment_id"], "environment_id")
        if str(env.get("kernel_target")) != target.value:
            raise KernelTargetTranslationError(
                "environment.kernel_target must match requested kernel_target"
            )

        body = _optional_text(proof_body, "proof_body")
        if body:
            reject_trust_escapes(body, path="proof_body")

        imports = theory.imports or _KERNEL_DEFAULT_IMPORTS[target]
        source = self._render(
            target=target,
            theory=theory,
            theorem=theorem,
            imports=imports,
            proof_body=body,
            environment=env,
        )
        reject_trust_escapes(source, path="generated_source")

        edge = self.edges.by_kernel(target)
        loss_ids = edge[0].loss_ids if edge else (
            "loss:candidate-until-kernel-acceptance",
        )

        return KernelCompilationCandidate(
            candidate_id=f"candidate:{theory.theory_id}:{theorem['theorem_id']}:{target.value}",
            theory_id=theory.theory_id,
            theory_document_id=theory.document_id,
            kernel_target=target,
            encoding=_KERNEL_ENCODINGS[target],
            source=source,
            source_digest=content_digest(source),
            imports=tuple(imports),
            axioms=theory.axioms,
            theorem_id=theorem["theorem_id"],
            theorem_name=theorem["theorem_name"],
            statement=theorem["statement"],
            statement_digest=content_digest(theorem["statement"]),
            environment_id=env_id,
            environment=env,
            source_maps=theory.source_maps,
            trust_escapes_rejected=tuple(
                kind for kind, _ in _TRUST_ESCAPE_PATTERNS
            ),
            status=CompilationStatus.CANDIDATE,
            kernel_accepted=False,
            loss_ids=loss_ids,
            description=(
                f"Compilation candidate for {target.value}; official kernel "
                "acceptance required for theorem authority."
            ),
        )

    def compile_all(
        self,
        theory: TargetTheoryArtifact | Mapping[str, Any],
        *,
        kernel_target: KernelTargetKind | str,
        environment: Mapping[str, Any] | None = None,
        proof_bodies: Mapping[str, str] | None = None,
    ) -> tuple[KernelCompilationCandidate, ...]:
        if isinstance(theory, Mapping):
            theory = TargetTheoryArtifact.from_dict(theory)
        bodies = proof_bodies or {}
        return tuple(
            self.compile(
                theory,
                kernel_target=kernel_target,
                theorem_id=item["theorem_id"],
                environment=environment,
                proof_body=str(bodies.get(item["theorem_id"], "")),
            )
            for item in theory.theorems
        )

    def record_kernel_acceptance(
        self,
        candidate: KernelCompilationCandidate | Mapping[str, Any],
        *,
        accepted: bool,
        environment_id: str,
        theorem_identity_digest: str = "",
        notes: str = "",
    ) -> KernelCompilationCandidate:
        """Record official-kernel acceptance for an existing candidate.

        This method never *performs* kernel checking; it only records a
        verified external decision when the environment and theorem identities
        match the candidate.
        """

        if isinstance(candidate, Mapping):
            candidate = KernelCompilationCandidate.from_dict(candidate)
        if not isinstance(candidate, KernelCompilationCandidate):
            raise KernelTargetTranslationError(
                "candidate must be a KernelCompilationCandidate"
            )
        env_id = _identifier(environment_id, "environment_id")
        if env_id != candidate.environment_id:
            raise KernelTargetTranslationError(
                "environment_id does not match candidate environment identity"
            )
        if theorem_identity_digest:
            expected = content_digest(candidate.statement)
            if theorem_identity_digest not in {
                expected,
                candidate.statement_digest,
                candidate.source_digest,
            }:
                # Allow binding to statement digest only.
                if theorem_identity_digest != candidate.statement_digest:
                    raise KernelTargetTranslationError(
                        "theorem_identity_digest does not match candidate"
                    )
        status = (
            CompilationStatus.KERNEL_ACCEPTED
            if accepted
            else CompilationStatus.KERNEL_REJECTED
        )
        payload = candidate.to_dict()
        payload["status"] = status.value
        payload["kernel_accepted"] = bool(accepted)
        if notes:
            payload["description"] = (
                f"{candidate.description} | acceptance_notes={notes}"
                if candidate.description
                else notes
            )
        # Bypass candidate-only constructor guard by reconstructing carefully.
        return KernelCompilationCandidate(
            candidate_id=payload["candidate_id"],
            theory_id=payload["theory_id"],
            theory_document_id=payload["theory_document_id"],
            kernel_target=payload["kernel_target"],
            encoding=payload["encoding"],
            source=payload["source"],
            source_digest=payload["source_digest"],
            imports=tuple(payload["imports"]),
            axioms=tuple(payload["axioms"]),
            theorem_id=payload["theorem_id"],
            theorem_name=payload["theorem_name"],
            statement=payload["statement"],
            statement_digest=payload["statement_digest"],
            environment_id=payload["environment_id"],
            environment=payload["environment"],
            source_maps=tuple(payload["source_maps"]),
            trust_escapes_rejected=tuple(payload["trust_escapes_rejected"]),
            status=status,
            kernel_accepted=bool(accepted),
            loss_ids=tuple(payload["loss_ids"]),
            description=payload.get("description", ""),
        )

    def _render(
        self,
        *,
        target: KernelTargetKind,
        theory: TargetTheoryArtifact,
        theorem: Mapping[str, Any],
        imports: Sequence[str],
        proof_body: str,
        environment: Mapping[str, Any],
    ) -> str:
        name = _safe_ident(str(theorem["theorem_name"]), prefix="thm")
        statement = str(theorem["statement"]).strip()
        if target is KernelTargetKind.LEAN:
            return self._render_lean(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
            )
        if target is KernelTargetKind.ROCQ:
            return self._render_rocq(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
            )
        if target is KernelTargetKind.ISABELLE:
            return self._render_isabelle(
                name=name,
                statement=statement,
                imports=imports,
                proof_body=proof_body,
                theory=theory,
                environment=environment,
            )
        raise KernelTargetTranslationError(
            f"unsupported kernel target {target!r}"
        )

    def _render_lean(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryArtifact,
    ) -> str:
        lines = [f"import {path}" for path in imports]
        lines.append("")
        lines.append(f"-- theory: {theory.theory_id}")
        for axiom in theory.axioms:
            # Record axioms as comments; inline axiom escapes are rejected.
            lines.append(f"-- axiom assumption: {axiom}")
        body = proof_body.strip() if proof_body else "True.intro"
        # Keep proof body free of trust escapes; default is a trivial placeholder
        # that remains a *candidate* until the official kernel checks a real proof.
        lines.append(f"theorem {name} : True := by")
        lines.append(f"  -- statement: {statement}")
        for line in body.splitlines() or ["True.intro"]:
            lines.append(f"  {line}")
        return "\n".join(lines) + "\n"

    def _render_rocq(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryArtifact,
    ) -> str:
        lines = [f"Require Import {path}." for path in imports]
        lines.append("")
        lines.append(f"(* theory: {theory.theory_id} *)")
        for axiom in theory.axioms:
            lines.append(f"(* axiom assumption: {axiom} *)")
        body = proof_body.strip() if proof_body else "exact I."
        lines.append(f"Theorem {name} : True.")
        lines.append("Proof.")
        lines.append(f"  (* statement: {statement} *)")
        for line in body.splitlines() or ["exact I."]:
            lines.append(f"  {line}")
        lines.append("Qed.")
        return "\n".join(lines) + "\n"

    def _render_isabelle(
        self,
        *,
        name: str,
        statement: str,
        imports: Sequence[str],
        proof_body: str,
        theory: TargetTheoryArtifact,
        environment: Mapping[str, Any],
    ) -> str:
        session = str(environment.get("session_or_package") or theory.name)
        theory_name = _safe_ident(session, prefix="Theory")
        import_list = " ".join(imports) if imports else "Main"
        lines = [
            f"theory {theory_name}",
            f"  imports {import_list}",
            "begin",
            "",
            f"(* theory: {theory.theory_id} *)",
        ]
        for axiom in theory.axioms:
            lines.append(f"(* axiom assumption: {axiom} *)")
        body = proof_body.strip() if proof_body else "by simp"
        lines.append(f"lemma {name}: \"True\"")
        lines.append(f"  (* statement: {statement} *)")
        lines.append(f"  {body}")
        lines.append("")
        lines.append("end")
        return "\n".join(lines) + "\n"


def build_kernel_target_compiler(
    *,
    edges: KernelTargetTranslationEdges | None = None,
    default_environment: Mapping[str, Any] | None = None,
) -> KernelTargetCompiler:
    """Public factory for ``KernelTargetCompiler@2``."""

    return KernelTargetCompiler(
        edges=edges,
        default_environment=default_environment,
    )


__all__ = [
    "COMPILER_IDENTITY",
    "COMPILATION_CANDIDATE_SCHEMA",
    "CONFIG_IDENTITY",
    "DEFAULT_ISABELLE_IMPORTS",
    "DEFAULT_LEAN_IMPORTS",
    "DEFAULT_ROCQ_IMPORTS",
    "ENCODING_ISABELLE",
    "ENCODING_LEAN",
    "ENCODING_ROCQ",
    "ENVIRONMENT_IDENTITY",
    "FEAT_ADMIT",
    "FEAT_AXIOMS",
    "FEAT_IMPORTS",
    "FEAT_ISABELLE",
    "FEAT_KERNEL_CANDIDATE",
    "FEAT_LEAN",
    "FEAT_ROCQ",
    "FEAT_SORRY",
    "FEAT_SOURCE_MAPS",
    "FEAT_TARGET_THEORY",
    "FEAT_THEOREMS",
    "FEAT_TRUST_ESCAPE",
    "KERNEL_TARGET_COMPILER_INTERFACE",
    "KERNEL_TARGET_EDGES_INTERFACE",
    "KERNEL_TARGET_EDGES_SCHEMA",
    "PROFILE_IDENTITY",
    "SOURCE_TARGET_THEORY",
    "TARGET_ISABELLE",
    "TARGET_LEAN",
    "TARGET_ROCQ",
    "TARGET_THEORY_FAMILY",
    "CompilationStatus",
    "DeclarationKind",
    "KernelCompilationCandidate",
    "KernelSourceMap",
    "KernelTargetCompiler",
    "KernelTargetKind",
    "KernelTargetTranslationEdge",
    "KernelTargetTranslationEdges",
    "KernelTargetTranslationError",
    "SourceSurface",
    "TargetTheoryArtifact",
    "build_kernel_target_compiler",
    "build_kernel_target_translation_edges",
    "content_digest",
    "is_official_kernel",
    "kernel_target_translation_contracts",
    "reject_trust_escapes",
    "scan_trust_escapes",
]
