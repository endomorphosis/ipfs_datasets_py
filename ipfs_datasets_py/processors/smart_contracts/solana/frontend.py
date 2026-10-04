"""Solana program frontend and deployment semantics (CRYPTOIR-G230).

Normalizes executable/program/program-data accounts, SBF ELF, loader state,
upgrade authority, IDL/source/build artifacts, instructions, CPI, and account
privilege/owner semantics into explicit, fail-closed records.

Privilege and owner checks are first-class semantics, not generic call
metadata.  Source claims without reproducible SBF equality remain evidence
only; deployed ELF is analyzed independently when reproduction fails.

Importing this module performs no network I/O, secret resolution, or package
installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..artifacts import bytes_digest
from ..canonical import content_digest, freeze_json, thaw_json
from ..errors import (
    ArtifactInconsistentError,
    InvalidRequestError,
    ResourceLimitError,
)
from ..models import ensure_secret_safe
from ..source import SourceFileRecord, SourceManifest, ToolchainPin
from .loader import (
    BPF_LOADER_UPGRADEABLE,
    LoaderVersion,
    ProgramAccountRelation,
    UpgradeAuthority,
    UpgradeAuthorityState,
    bind_program_relation,
    bind_upgrade_authority,
    classify_loader,
    normalize_pubkey,
)
from .provider import OfflineSolanaProvider, SolanaProgramFixture
from .semantics import (
    DEFAULT_MAX_ELF_BYTES,
    AccountPrivilege,
    CPIEdge,
    CPIGraph,
    OwnerCheck,
    PDAConstraint,
    SemanticPassStatus,
    assert_elf_magic,
    build_cpi_graph,
    incomplete_coverage_never_passes,
    normalize_elf_bytes,
)


FRONTEND_SCHEMA_VERSION = "smart-contract-solana-frontend-v1"
FRONTEND_ID = "smart-contracts.solana.frontend"
FRONTEND_VERSION = "1.0.0"


class SourceEquivalenceStatus(StrEnum):
    """Whether IDL/source was reproducibly bound to deployed SBF ELF."""

    REPRODUCED = "reproduced"
    NOT_DECLARED = "not_declared"
    MISMATCH = "mismatch"
    INDEPENDENT_RUNTIME = "independent_runtime"
    UNAVAILABLE = "unavailable"
    EVIDENCE_ONLY = "evidence_only"


class AnalysisMode(StrEnum):
    """How the frontend treated source relative to deployed program bytes."""

    SOURCE_AND_RUNTIME = "source_and_runtime"
    RUNTIME_ONLY = "runtime_only"
    SOURCE_EVIDENCE_ONLY = "source_evidence_only"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _optional_digest(value: str, name: str) -> str:
    if not value:
        return ""
    text = _required_text(value, name)
    if not text.startswith("sha256:"):
        raise InvalidRequestError(f"{name} must be a tagged sha256 digest")
    return text


@dataclass(frozen=True, slots=True)
class ProgramDataEpoch:
    """Bound program-data epoch for one Solana program at a cluster coordinate.

    Artifacts bind cluster, program id, loader version, executable/program-data
    relation, binary hash, deployment slot, upgrade authority, and IDL/build
    correspondence.  Empty optional fields mean "unbound evidence" rather than
    a silent default.
    """

    chain_id: str
    program_id: str
    binary_digest: str
    loader_version: LoaderVersion
    loader_program_id: str
    deployment_slot: int | None = None
    code_epoch: str = ""
    program_data_address: str = ""
    upgrade_authority: UpgradeAuthority | None = None
    idl_digest: str = ""
    build_manifest_digest: str = ""
    compiler: str = ""
    compiler_version: str = ""
    compiler_flags: Mapping[str, Any] = field(default_factory=dict)
    network: str = ""
    genesis_hash: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _required_text(self.chain_id, "chain_id"))
        object.__setattr__(
            self, "program_id", normalize_pubkey(self.program_id, field="program_id")
        )
        object.__setattr__(
            self,
            "binary_digest",
            _optional_digest(self.binary_digest, "binary_digest")
            if self.binary_digest
            else "",
        )
        loader = (
            self.loader_version
            if isinstance(self.loader_version, LoaderVersion)
            else LoaderVersion(str(self.loader_version))
        )
        object.__setattr__(self, "loader_version", loader)
        object.__setattr__(
            self,
            "loader_program_id",
            normalize_pubkey(self.loader_program_id, field="loader_program_id"),
        )
        if self.deployment_slot is not None:
            object.__setattr__(
                self,
                "deployment_slot",
                _non_negative(self.deployment_slot, "deployment_slot"),
            )
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
        )
        if self.program_data_address:
            object.__setattr__(
                self,
                "program_data_address",
                normalize_pubkey(
                    self.program_data_address, field="program_data_address"
                ),
            )
        else:
            object.__setattr__(self, "program_data_address", "")
        if self.upgrade_authority is not None and not isinstance(
            self.upgrade_authority, UpgradeAuthority
        ):
            raise InvalidRequestError(
                "upgrade_authority must be an UpgradeAuthority or None"
            )
        object.__setattr__(
            self,
            "idl_digest",
            _optional_digest(self.idl_digest, "idl_digest") if self.idl_digest else "",
        )
        object.__setattr__(
            self,
            "build_manifest_digest",
            _optional_digest(self.build_manifest_digest, "build_manifest_digest")
            if self.build_manifest_digest
            else "",
        )
        object.__setattr__(
            self, "compiler", self.compiler.strip() if self.compiler else ""
        )
        object.__setattr__(
            self,
            "compiler_version",
            self.compiler_version.strip() if self.compiler_version else "",
        )
        object.__setattr__(
            self, "compiler_flags", _freeze_mapping(self.compiler_flags)
        )
        object.__setattr__(
            self, "network", self.network.strip() if self.network else ""
        )
        object.__setattr__(
            self, "genesis_hash", self.genesis_hash.strip() if self.genesis_hash else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, "schema_version"),
        )
        ensure_secret_safe(self.to_dict())

    @property
    def record_id(self) -> str:
        return content_digest(
            {
                "binary_digest": self.binary_digest,
                "chain_id": self.chain_id,
                "code_epoch": self.code_epoch,
                "deployment_slot": self.deployment_slot,
                "program_id": self.program_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "binary_digest": self.binary_digest,
            "build_manifest_digest": self.build_manifest_digest,
            "chain_id": self.chain_id,
            "code_epoch": self.code_epoch,
            "compiler": self.compiler,
            "compiler_flags": thaw_json(self.compiler_flags),
            "compiler_version": self.compiler_version,
            "deployment_slot": self.deployment_slot,
            "genesis_hash": self.genesis_hash,
            "idl_digest": self.idl_digest,
            "loader_program_id": self.loader_program_id,
            "loader_version": self.loader_version.value
            if isinstance(self.loader_version, LoaderVersion)
            else str(self.loader_version),
            "network": self.network,
            "program_data_address": self.program_data_address,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "upgrade_authority": self.upgrade_authority.to_dict()
            if self.upgrade_authority is not None
            else None,
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_fixture(
        cls,
        fixture: SolanaProgramFixture,
        *,
        network: str = "",
        genesis_hash: str = "",
    ) -> "ProgramDataEpoch":
        """Build an epoch binding from an offline fixture (no network)."""

        if not isinstance(fixture, SolanaProgramFixture):
            raise InvalidRequestError("fixture must be a SolanaProgramFixture")
        binary_digest = fixture.sbf_elf_digest
        if not binary_digest:
            raise InvalidRequestError(
                "fixture must provide SBF ELF for a program-data epoch"
            )
        code_epoch = fixture.code_epoch
        if not code_epoch:
            code_epoch = f"sbf:{binary_digest}"
        authority = fixture.upgrade_authority_record()
        return cls(
            chain_id=fixture.chain_id,
            program_id=fixture.program_id,
            binary_digest=binary_digest,
            loader_version=fixture.loader_version,
            loader_program_id=fixture.loader_program_id,
            deployment_slot=fixture.deployment_slot,
            code_epoch=code_epoch,
            program_data_address=fixture.program_data_address,
            upgrade_authority=authority,
            idl_digest=bytes_digest(fixture.idl_json) if fixture.idl_json else "",
            build_manifest_digest=bytes_digest(fixture.build_manifest_json)
            if fixture.build_manifest_json
            else "",
            compiler=fixture.compiler,
            compiler_version=fixture.compiler_version,
            compiler_flags=dict(fixture.compiler_flags),
            network=network,
            genesis_hash=genesis_hash,
            attributes=dict(fixture.attributes),
        )


@dataclass(frozen=True, slots=True)
class SolanaNormalizationResult:
    """Full frontend output for one Solana program observation."""

    program_epoch: ProgramDataEpoch
    program_relation: ProgramAccountRelation
    upgrade_authority: UpgradeAuthority
    cpi_graph: CPIGraph
    source_equivalence: SourceEquivalenceStatus
    analysis_mode: AnalysisMode
    semantic_pass_status: SemanticPassStatus
    diagnostics: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FRONTEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.program_epoch, ProgramDataEpoch):
            raise InvalidRequestError("program_epoch must be a ProgramDataEpoch")
        if not isinstance(self.program_relation, ProgramAccountRelation):
            raise InvalidRequestError(
                "program_relation must be a ProgramAccountRelation"
            )
        if not isinstance(self.upgrade_authority, UpgradeAuthority):
            raise InvalidRequestError("upgrade_authority must be an UpgradeAuthority")
        if not isinstance(self.cpi_graph, CPIGraph):
            raise InvalidRequestError("cpi_graph must be a CPIGraph")
        object.__setattr__(
            self,
            "source_equivalence",
            self.source_equivalence
            if isinstance(self.source_equivalence, SourceEquivalenceStatus)
            else SourceEquivalenceStatus(str(self.source_equivalence)),
        )
        object.__setattr__(
            self,
            "analysis_mode",
            self.analysis_mode
            if isinstance(self.analysis_mode, AnalysisMode)
            else AnalysisMode(str(self.analysis_mode)),
        )
        object.__setattr__(
            self,
            "semantic_pass_status",
            self.semantic_pass_status
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else SemanticPassStatus(str(self.semantic_pass_status)),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _required_text(item, "diagnostics item") for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        # Invariant: incomplete coverage never passes.
        if self.semantic_pass_status is SemanticPassStatus.PASS:
            if not self.cpi_graph.inner_instruction_coverage:
                raise InvalidRequestError(
                    "semantic pass forbidden without inner instruction coverage"
                )
        ensure_secret_safe(self.to_dict())

    @property
    def is_pass(self) -> bool:
        return self.semantic_pass_status is SemanticPassStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode.value
            if isinstance(self.analysis_mode, AnalysisMode)
            else str(self.analysis_mode),
            "attributes": thaw_json(self.attributes),
            "cpi_graph": self.cpi_graph.to_dict(),
            "diagnostics": list(self.diagnostics),
            "program_epoch": self.program_epoch.to_dict(),
            "program_relation": self.program_relation.to_dict(),
            "schema_version": self.schema_version,
            "semantic_pass_status": self.semantic_pass_status.value
            if isinstance(self.semantic_pass_status, SemanticPassStatus)
            else str(self.semantic_pass_status),
            "source_equivalence": self.source_equivalence.value
            if isinstance(self.source_equivalence, SourceEquivalenceStatus)
            else str(self.source_equivalence),
            "upgrade_authority": self.upgrade_authority.to_dict(),
        }

    def content_digest(self) -> str:
        return content_digest(self.to_dict())


class SolanaProgramFrontend:
    """Acquire/normalize Solana programs into Crypto IR-oriented records.

    Designed for offline fixtures by default.  An optional
    :class:`OfflineSolanaProvider` may be injected; the frontend itself never
    opens sockets.
    """

    def __init__(
        self,
        *,
        provider: OfflineSolanaProvider | None = None,
        max_elf_bytes: int = DEFAULT_MAX_ELF_BYTES,
        require_elf_magic: bool = True,
    ) -> None:
        if (
            isinstance(max_elf_bytes, bool)
            or not isinstance(max_elf_bytes, int)
            or max_elf_bytes <= 0
        ):
            raise InvalidRequestError("max_elf_bytes must be a positive integer")
        self._provider = provider
        self._max_elf_bytes = max_elf_bytes
        self._require_elf_magic = bool(require_elf_magic)

    @property
    def frontend_id(self) -> str:
        return FRONTEND_ID

    @property
    def version(self) -> str:
        return FRONTEND_VERSION

    @property
    def provider(self) -> OfflineSolanaProvider | None:
        return self._provider

    def bind_program_epoch(
        self,
        *,
        chain_id: str,
        program_id: str,
        sbf_elf: bytes | str,
        loader_program_id: str = BPF_LOADER_UPGRADEABLE,
        deployment_slot: int | None = None,
        code_epoch: str = "",
        program_data_address: str = "",
        upgrade_authority_pubkey: str | None = None,
        idl: bytes | str = b"",
        build_manifest: bytes | str = b"",
        compiler: str = "",
        compiler_version: str = "",
        compiler_flags: Mapping[str, Any] | None = None,
        network: str = "",
        genesis_hash: str = "",
        attributes: Mapping[str, Any] | None = None,
        require_elf_magic: bool | None = None,
    ) -> ProgramDataEpoch:
        """Bind cluster/program/slot/loader/binary and build metadata to digests."""

        elf = normalize_elf_bytes(sbf_elf)
        if len(elf) > self._max_elf_bytes:
            raise ResourceLimitError("SBF ELF exceeds max_elf_bytes")
        check_magic = (
            self._require_elf_magic if require_elf_magic is None else require_elf_magic
        )
        if check_magic:
            assert_elf_magic(elf)

        binary_digest = bytes_digest(elf)
        if not binary_digest:
            raise InvalidRequestError("SBF ELF is required for program-data epoch binding")

        loader_version = classify_loader(loader_program_id)
        epoch_label = code_epoch.strip() if code_epoch else f"sbf:{binary_digest}"

        idl_bytes = _as_bytes(idl)
        build_bytes = _as_bytes(build_manifest)

        authority = bind_upgrade_authority(
            authority_pubkey=upgrade_authority_pubkey,
            program_data_address=program_data_address,
            slot_observed=deployment_slot,
            loader_version=loader_version,
        )

        return ProgramDataEpoch(
            chain_id=chain_id,
            program_id=program_id,
            binary_digest=binary_digest,
            loader_version=loader_version,
            loader_program_id=loader_program_id,
            deployment_slot=deployment_slot,
            code_epoch=epoch_label,
            program_data_address=program_data_address,
            upgrade_authority=authority,
            idl_digest=bytes_digest(idl_bytes) if idl_bytes else "",
            build_manifest_digest=bytes_digest(build_bytes) if build_bytes else "",
            compiler=compiler,
            compiler_version=compiler_version,
            compiler_flags=dict(compiler_flags or {}),
            network=network,
            genesis_hash=genesis_hash,
            attributes=dict(attributes or {}),
        )

    def reproduce_sbf_equivalence(
        self,
        source_manifest: SourceManifest,
        *,
        sbf_elf: bytes | str | None = None,
    ) -> SourceEquivalenceStatus:
        """Reproduce source/deployed SBF equality; never trust provider claims alone.

        Uses ``runtime_bytecode_digest`` on the source manifest as the declared
        SBF ELF digest (shared source-manifest surface).
        """

        if not isinstance(source_manifest, SourceManifest):
            raise InvalidRequestError("source_manifest must be a SourceManifest")

        has_declared = bool(
            source_manifest.runtime_bytecode_digest
            or source_manifest.creation_bytecode_digest
        )
        if not has_declared:
            return SourceEquivalenceStatus.NOT_DECLARED

        if sbf_elf is None:
            return SourceEquivalenceStatus.UNAVAILABLE

        elf = normalize_elf_bytes(sbf_elf)
        try:
            source_manifest.assert_deployed_equivalence(
                creation=None,
                runtime=elf,
            )
        except ArtifactInconsistentError:
            return SourceEquivalenceStatus.MISMATCH
        return SourceEquivalenceStatus.REPRODUCED

    def analyze_cpi(
        self,
        *,
        program_id: str,
        edges: Sequence[CPIEdge] = (),
        privileges: Sequence[AccountPrivilege] = (),
        pda_constraints: Sequence[PDAConstraint] = (),
        owner_checks: Sequence[OwnerCheck] = (),
        inner_instruction_coverage: bool = False,
        claim_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
    ) -> CPIGraph:
        """Build CPI graph with first-class privilege and owner checks."""

        graph = build_cpi_graph(
            program_id=program_id,
            edges=edges,
            privileges=privileges,
            pda_constraints=pda_constraints,
            owner_checks=owner_checks,
            inner_instruction_coverage=inner_instruction_coverage,
            claim_pass=claim_pass,
            attributes=attributes,
        )
        # Double-guard incomplete coverage.
        status = incomplete_coverage_never_passes(graph=graph, claim_pass=claim_pass)
        if status is not graph.pass_status:
            return CPIGraph(
                program_id=graph.program_id,
                edges=graph.edges,
                privileges=graph.privileges,
                pda_constraints=graph.pda_constraints,
                owner_checks=graph.owner_checks,
                inner_instruction_coverage=graph.inner_instruction_coverage,
                coverage_notes=graph.coverage_notes,
                pass_status=status,
                diagnostics=graph.diagnostics
                + ("pass status adjusted by incomplete-coverage guard",),
                attributes=dict(graph.attributes),
            )
        return graph

    def normalize_program(
        self,
        *,
        chain_id: str,
        program_id: str,
        sbf_elf: bytes | str,
        loader_program_id: str = BPF_LOADER_UPGRADEABLE,
        deployment_slot: int | None = None,
        code_epoch: str = "",
        program_data_address: str = "",
        upgrade_authority_pubkey: str | None = None,
        idl: bytes | str = b"",
        build_manifest: bytes | str = b"",
        compiler: str = "",
        compiler_version: str = "",
        compiler_flags: Mapping[str, Any] | None = None,
        network: str = "",
        genesis_hash: str = "",
        source_manifest: SourceManifest | None = None,
        edges: Sequence[CPIEdge] = (),
        privileges: Sequence[AccountPrivilege] = (),
        pda_constraints: Sequence[PDAConstraint] = (),
        owner_checks: Sequence[OwnerCheck] = (),
        inner_instruction_coverage: bool = False,
        claim_semantic_pass: bool = False,
        attributes: Mapping[str, Any] | None = None,
        require_elf_magic: bool | None = None,
    ) -> SolanaNormalizationResult:
        """Full normalization: epoch, loader relation, upgrade, CPI, source policy.

        When *source_manifest* is absent or SBF equivalence cannot be
        reproduced, deployed ELF is analyzed independently
        (:attr:`AnalysisMode.RUNTIME_ONLY` /
        :attr:`SourceEquivalenceStatus.INDEPENDENT_RUNTIME`).
        """

        elf = normalize_elf_bytes(sbf_elf)
        if len(elf) > self._max_elf_bytes:
            raise ResourceLimitError("SBF ELF exceeds max_elf_bytes")
        check_magic = (
            self._require_elf_magic if require_elf_magic is None else require_elf_magic
        )
        if check_magic:
            assert_elf_magic(elf)

        epoch = self.bind_program_epoch(
            chain_id=chain_id,
            program_id=program_id,
            sbf_elf=elf,
            loader_program_id=loader_program_id,
            deployment_slot=deployment_slot,
            code_epoch=code_epoch,
            program_data_address=program_data_address,
            upgrade_authority_pubkey=upgrade_authority_pubkey,
            idl=idl,
            build_manifest=build_manifest,
            compiler=compiler,
            compiler_version=compiler_version,
            compiler_flags=compiler_flags,
            network=network,
            genesis_hash=genesis_hash,
            attributes=attributes,
            require_elf_magic=False,  # already checked
        )

        relation = bind_program_relation(
            program_id=program_id,
            loader_program_id=loader_program_id,
            program_data_address=program_data_address,
            sbf_elf=elf,
            deployment_slot=deployment_slot,
        )
        authority = epoch.upgrade_authority or bind_upgrade_authority(
            authority_pubkey=upgrade_authority_pubkey,
            program_data_address=program_data_address,
            slot_observed=deployment_slot,
            loader_version=epoch.loader_version,
        )

        cpi = self.analyze_cpi(
            program_id=program_id,
            edges=edges,
            privileges=privileges,
            pda_constraints=pda_constraints,
            owner_checks=owner_checks,
            inner_instruction_coverage=inner_instruction_coverage,
            claim_pass=claim_semantic_pass,
            attributes=attributes,
        )

        diagnostics: list[str] = list(cpi.diagnostics)
        if authority.diagnostics:
            diagnostics.extend(authority.diagnostics)

        # Source / IDL equivalence policy.
        if source_manifest is None:
            source_status = SourceEquivalenceStatus.INDEPENDENT_RUNTIME
            analysis_mode = AnalysisMode.RUNTIME_ONLY
            diagnostics.append(
                "no source manifest; analyzing deployed SBF independently"
            )
        else:
            source_status = self.reproduce_sbf_equivalence(
                source_manifest, sbf_elf=elf
            )
            if source_status is SourceEquivalenceStatus.REPRODUCED:
                analysis_mode = AnalysisMode.SOURCE_AND_RUNTIME
                diagnostics.append(
                    "source/deployed SBF equivalence reproduced by digest match"
                )
            elif source_status is SourceEquivalenceStatus.MISMATCH:
                analysis_mode = AnalysisMode.RUNTIME_ONLY
                source_status = SourceEquivalenceStatus.INDEPENDENT_RUNTIME
                diagnostics.append(
                    "source claim failed SBF reproduction; analyzing ELF independently"
                )
            elif source_status is SourceEquivalenceStatus.NOT_DECLARED:
                analysis_mode = AnalysisMode.SOURCE_EVIDENCE_ONLY
                source_status = SourceEquivalenceStatus.EVIDENCE_ONLY
                diagnostics.append(
                    "source present without declared SBF digests; evidence only"
                )
            else:
                analysis_mode = AnalysisMode.RUNTIME_ONLY
                diagnostics.append(
                    "source binding unavailable; analyzing SBF independently"
                )

        # IDL/build correspondence notes.
        if epoch.idl_digest:
            diagnostics.append(f"IDL bound by digest {epoch.idl_digest}")
        else:
            diagnostics.append("IDL not bound; interface correspondence unbound")
        if epoch.build_manifest_digest:
            diagnostics.append(
                f"build manifest bound by digest {epoch.build_manifest_digest}"
            )

        if authority.state is UpgradeAuthorityState.UNKNOWN:
            diagnostics.append("upgrade authority unknown; immutability not assumed")
        if authority.state is UpgradeAuthorityState.AUTHORITY_SET:
            diagnostics.append(
                f"program upgradeable under authority {authority.authority_pubkey}"
            )
        if authority.state is UpgradeAuthorityState.IMMUTABLE:
            diagnostics.append("upgrade authority revoked; program immutable")

        semantic_status = cpi.pass_status
        attrs = dict(attributes or {})
        attrs["inner_instruction_coverage"] = inner_instruction_coverage
        attrs["loader_version"] = epoch.loader_version.value
        attrs["binary_digest"] = epoch.binary_digest

        if claim_semantic_pass and semantic_status is not SemanticPassStatus.PASS:
            diagnostics.append("semantic pass claim rejected by fail-closed gate")
        elif not claim_semantic_pass and semantic_status is SemanticPassStatus.PASS:
            # Should not happen given build_cpi_graph policy, but guard.
            semantic_status = SemanticPassStatus.INCOMPLETE
            diagnostics.append("pass suppressed without explicit claim")

        return SolanaNormalizationResult(
            program_epoch=epoch,
            program_relation=relation,
            upgrade_authority=authority,
            cpi_graph=cpi,
            source_equivalence=source_status,
            analysis_mode=analysis_mode,
            semantic_pass_status=semantic_status,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            attributes=attrs,
        )

    def normalize_fixture(
        self,
        fixture: SolanaProgramFixture,
        *,
        source_manifest: SourceManifest | None = None,
        network: str = "",
        genesis_hash: str = "",
        edges: Sequence[CPIEdge] = (),
        privileges: Sequence[AccountPrivilege] = (),
        pda_constraints: Sequence[PDAConstraint] = (),
        owner_checks: Sequence[OwnerCheck] = (),
        inner_instruction_coverage: bool = False,
        claim_semantic_pass: bool = False,
        require_elf_magic: bool | None = None,
    ) -> SolanaNormalizationResult:
        """Normalize an offline fixture (golden SBF path)."""

        if not isinstance(fixture, SolanaProgramFixture):
            raise InvalidRequestError("fixture must be a SolanaProgramFixture")
        if not fixture.sbf_elf:
            raise InvalidRequestError("fixture sbf_elf is required")

        # Materialize owner checks from fixture account_owners when none given.
        checks = list(owner_checks)
        if not checks and fixture.account_owners:
            from .semantics import check_account_owner

            for account, owner in fixture.account_owners.items():
                checks.append(
                    check_account_owner(
                        account_pubkey=account,
                        expected_owner=fixture.program_id,
                        observed_owner=owner,
                    )
                )

        return self.normalize_program(
            chain_id=fixture.chain_id,
            program_id=fixture.program_id,
            sbf_elf=fixture.sbf_elf,
            loader_program_id=fixture.loader_program_id,
            deployment_slot=fixture.deployment_slot,
            code_epoch=fixture.code_epoch,
            program_data_address=fixture.program_data_address,
            upgrade_authority_pubkey=fixture.upgrade_authority,
            idl=fixture.idl_json,
            build_manifest=fixture.build_manifest_json,
            compiler=fixture.compiler,
            compiler_version=fixture.compiler_version,
            compiler_flags=dict(fixture.compiler_flags),
            network=network,
            genesis_hash=genesis_hash,
            source_manifest=source_manifest,
            edges=edges,
            privileges=privileges,
            pda_constraints=pda_constraints,
            owner_checks=checks,
            inner_instruction_coverage=inner_instruction_coverage,
            claim_semantic_pass=claim_semantic_pass,
            attributes=dict(fixture.attributes),
            require_elf_magic=require_elf_magic,
        )

    def build_source_manifest(
        self,
        *,
        request_id: str,
        sources: Mapping[str, bytes],
        compiler: str,
        compiler_version: str,
        settings: Mapping[str, Any] | None = None,
        sbf_elf: bytes | str = b"",
        idl: bytes | str = b"",
        code_epoch: str = "",
        observed_at: datetime | None = None,
        language: str = "rust",
    ) -> SourceManifest:
        """Build a reproducible source manifest binding expected SBF digests."""

        files = tuple(
            SourceFileRecord.from_bytes(path, payload, language=language)
            for path, payload in sorted(sources.items())
        )
        toolchain = ToolchainPin(
            compiler=compiler,
            compiler_version=compiler_version,
            settings=dict(settings or {}),
            target="sbf",
        )
        elf = normalize_elf_bytes(sbf_elf) if sbf_elf else b""
        idl_bytes = _as_bytes(idl)
        return SourceManifest(
            files=files,
            toolchain=toolchain,
            request_id=request_id,
            observed_at=observed_at or datetime.now(timezone.utc),
            runtime_bytecode_digest=bytes_digest(elf) if elf else "",
            interface_digest=bytes_digest(idl_bytes) if idl_bytes else "",
            metadata_policy="solana-sbf-none",
            code_epoch=code_epoch,
        )


def _as_bytes(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str) and value:
        return value.encode("utf-8")
    return b""


__all__ = [
    "FRONTEND_ID",
    "FRONTEND_SCHEMA_VERSION",
    "FRONTEND_VERSION",
    "AnalysisMode",
    "ProgramDataEpoch",
    "SolanaNormalizationResult",
    "SolanaProgramFrontend",
    "SourceEquivalenceStatus",
]
