"""Live, receipt-bearing HSSL-G210 proof-runtime bridge.

G200 semantic results are immutable inputs to this module.  The bridge never
re-invokes the compiler, spaCy, or SyMAI and never gives their source-only
records the reviewed proof context.  It exposes that context only to the
preregistered proof stages and the independent native kernel.

The bridge is deliberately separate from the frozen revision-1 runner.  A
caller must provide one shared, explicit compiler-reference exposure receipt
per case/cache coordinate.  Candidate absence is therefore evidence from an
invoked compiler reference, not an unobserved ``None`` value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence, Self

from .adapters import (
    StageAdapter,
    StageArtifact,
    StageInvocation,
    StageOutput,
    StageRequest,
    semantic_context_binding,
)
from .content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    sha256_digest_for_cid,
    validate_cid,
)
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    DEFAULT_PROTOCOL_SHA256,
    SEMANTIC_PROTOCOL_V2_CID,
    CaseResultRecord,
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    Split,
    StageName,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
    validate_causal_proof_selection_receipt,
    validate_native_kernel_receipt,
)
from .metrics import (
    build_causal_rescue_case_receipt,
    validate_causal_rescue_case_receipt,
)
from .runtime import (
    CAUSAL_PROOF_HAMMER_FAILURE_CODES_V2,
    NATIVE_PROOF_CANDIDATE_SCHEMA,
    CausalKernelCheck,
    CausalProofCandidate,
    CausalProofFailure,
    CausalProofGraphController,
    CausalProofGraphResult,
    RuntimeBindingError,
    _entailment_translation,
    compile_reviewed_obligation,
    kernel_input_semantic_context,
)
from .variants import get_causal_proof_variant_profile, get_variant_definition


COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "compiler-reference-exposure.v2"
)
CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-runtime-evidence.v2"
)
G210_PROOF_COMPILER_BINDING_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "reviewed-proof-compiler-binding.v2"
)
_PROOF_STAGES: Final = frozenset(
    {StageName.HAMMER, StageName.LEANSTRAL}
)
_FRONTEND_STAGES: Final = frozenset(
    {StageName.COMPILER, StageName.SPACY, StageName.SYMAI}
)


class CausalRuntimeBridgeError(ValueError):
    """Raised when live G210 evidence cannot be represented truthfully."""


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _freeze_plain_json(value: object) -> object:
    """Deeply detach and freeze a value after semantic enum normalization."""

    plain = _plain(value)
    if isinstance(plain, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_plain_json(member)
                for key, member in plain.items()
            }
        )
    if isinstance(plain, list):
        return tuple(_freeze_plain_json(member) for member in plain)
    if plain is None or type(plain) in {str, bool, int, float}:
        return plain
    raise CausalRuntimeBridgeError(
        "causal runtime evidence contains a non-JSON value"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CausalRuntimeBridgeError(f"{field} must be an object")
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise CausalRuntimeBridgeError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _stage_artifact(
    record: StageRecord,
    *,
    invocation_index: int,
    policy_reason: str,
) -> StageArtifact:
    invoked = record.provenance.effective_identity.get("graph_invoked")
    if type(invoked) is not bool:
        raise CausalRuntimeBridgeError(
            f"{record.stage.value} record lacks an invocation decision"
        )
    return StageArtifact(
        stage=record.stage,
        status=record.status,
        data=_plain(record.data),
        output_sha256=record.output_sha256,
        effective_identity=_plain(
            record.provenance.effective_identity
        ),  # type: ignore[arg-type]
        invocation_index=invocation_index,
        invoked=invoked,
        policy_reason=policy_reason,
    )


def _artifact_bytes(artifact: StageArtifact) -> bytes:
    """Return the exact legacy-canonical bytes covered by artifact.digest."""

    return canonical_json(artifact.to_dict()).encode("utf-8")


def _artifact_cid(artifact: StageArtifact) -> str:
    """Use a raw CID because StageArtifact's frozen bytes are not DAG-JSON."""

    return cid_for_bytes(_artifact_bytes(artifact))


def _artifact_sha256(artifact: StageArtifact) -> str:
    return hashlib.sha256(_artifact_bytes(artifact)).hexdigest()


def _proof_compiler_binding(
    compiler_exposure: "CompilerReferenceExposureV2",
    *,
    source_text: str,
    proof_context: Mapping[str, object],
) -> tuple[StageArtifact, CausalProofCandidate | None]:
    """Build the proof-bound compiler artifact outside the G200 frontend.

    The semantic-v2 compiler is intentionally source-only and therefore
    cannot emit a reviewed obligation or a native proof candidate.  G210 owns
    that distinct operation: it deterministically joins the exact source,
    reviewed proof context, and source-only A0 exposure into a new artifact.
    The helper is shared by execution and validation, so neither a caller nor
    a persisted receipt can substitute proof-bearing bytes into the semantic
    compiler record.
    """

    if (
        not isinstance(compiler_exposure, CompilerReferenceExposureV2)
        or compiler_exposure.source_cid
        != cid_for_bytes(source_text.encode("utf-8"))
    ):
        raise CausalRuntimeBridgeError(
            "proof compiler binding differs from the source-only A0 exposure"
        )
    proof_context_value = _mapping(
        proof_context, "proof compiler reviewed context"
    )
    proof_input = {
        "text": source_text,
        **_plain(proof_context_value),  # type: ignore[arg-type]
    }
    try:
        compiled = compile_reviewed_obligation(proof_input)
    except RuntimeBindingError as exc:
        raise CausalRuntimeBridgeError(
            "reviewed proof compiler binding could not compile"
        ) from exc
    if compiled is None:
        raise CausalRuntimeBridgeError(
            "reviewed proof compiler binding lacks an obligation"
        )
    translation = _entailment_translation(
        proof_input,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    native_candidate = (
        None
        if translation is None or translation.native_proof_text is None
        else {
            "schema": NATIVE_PROOF_CANDIDATE_SCHEMA,
            "translation_sha256": translation.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "source_sha256": translation.source_sha256,
            "derivation": translation.shape,
            "certificate": translation.native_proof_text,
            "authoritative": False,
            "requires_independent_kernel": True,
        }
    )
    # Preserve replay compatibility for already-issued v2 evidence whose A0
    # exposure contained the exact reviewed compiler fields.  New semantic-v2
    # production execution never takes this branch: its compiler-output.v2 is
    # source-only and contains none of these fields.  Equality against a fresh
    # source+context compilation prevents a stale or substituted legacy
    # exposure from acquiring proof authority.
    exposed_data = compiler_exposure.compiler_record.data
    exposed_candidate = compiler_exposure.compiler_candidate
    if (
        isinstance(exposed_data, Mapping)
        and exposed_data.get("compiled_obligation") == compiled.to_dict()
        and exposed_data.get("compiled_obligation_sha256") == compiled.digest
        and exposed_data.get("entailment_translation")
        == (None if translation is None else translation.to_dict())
        and exposed_data.get("entailment_translation_sha256")
        == (None if translation is None else translation.digest)
        and exposed_data.get("native_proof_candidate") == native_candidate
        and (
            (native_candidate is None and exposed_candidate is None)
            or (
                native_candidate is not None
                and exposed_candidate is not None
                and exposed_candidate.certificate.decode("utf-8")
                == native_candidate["certificate"]
            )
        )
    ):
        return compiler_exposure.artifact, exposed_candidate
    proof_context_cid = cid_for_dag_json(_plain(proof_context_value))
    payload = {
        "schema": G210_PROOF_COMPILER_BINDING_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "source_cid": compiler_exposure.source_cid,
        "proof_context_cid": proof_context_cid,
        "compiler_reference_exposure_cid": (
            compiler_exposure.receipt_cid
        ),
        "compiled_obligation": compiled.to_dict(),
        "compiled_obligation_sha256": compiled.digest,
        "entailment_translation": (
            None if translation is None else translation.to_dict()
        ),
        "entailment_translation_sha256": (
            None if translation is None else translation.digest
        ),
        "native_proof_candidate": native_candidate,
    }
    artifact = StageArtifact(
        stage=StageName.COMPILER,
        status=StageStatus.SUCCESS,
        data=payload,
        output_sha256=None,
        effective_identity={
            "implementation": "g210-reviewed-proof-compiler",
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "source_cid": compiler_exposure.source_cid,
            "proof_context_cid": proof_context_cid,
            "compiler_reference_exposure_cid": (
                compiler_exposure.receipt_cid
            ),
        },
        invocation_index=0,
        invoked=True,
        policy_reason="g210_reviewed_proof_compiler_binding",
    )
    candidate = (
        None
        if native_candidate is None
        else CausalProofCandidate(
            source=StageName.COMPILER.value,
            certificate=str(native_candidate["certificate"]),
            artifact_cid=_artifact_cid(artifact),
        )
    )
    return artifact, candidate


def _legacy_source_input_sha256(source_text: str) -> str:
    """Return the frozen v1 input join for a semantic-v2 source envelope."""

    return hashlib.sha256(
        canonical_json({"text": source_text}).encode("utf-8")
    ).hexdigest()


def _semantic_requested_identity(
    variant_id: str,
    stage: StageName,
    source_cid: str,
) -> dict[str, object]:
    """Rebuild one exact source-only requested treatment identity."""

    identity = dict(
        get_variant_definition(variant_id).requested_identity(stage)
    )
    identity.update(
        {
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": source_cid,
            "proof_context_cid": None,
        }
    )
    return identity


def _candidate_to_dict(
    candidate: CausalProofCandidate | None,
) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "source": candidate.source,
        "certificate_utf8": candidate.certificate.decode("utf-8"),
        "candidate_cid": candidate.candidate_cid,
        "artifact_cid": candidate.artifact_cid,
    }


def _candidate_from_dict(value: object) -> CausalProofCandidate | None:
    if value is None:
        return None
    data = _mapping(value, "compiler_candidate")
    _exact(
        data,
        {"source", "certificate_utf8", "candidate_cid", "artifact_cid"},
        "compiler_candidate",
    )
    if not isinstance(data["certificate_utf8"], str):
        raise CausalRuntimeBridgeError(
            "compiler candidate certificate must be UTF-8 text"
        )
    return CausalProofCandidate(
        source=str(data["source"]),
        certificate=data["certificate_utf8"],
        candidate_cid=str(data["candidate_cid"]),
        artifact_cid=str(data["artifact_cid"]),
    )


def _compiler_record_certificate(record: StageRecord) -> str | None:
    if not isinstance(record.data, Mapping):
        return None
    value = record.data.get("native_proof_candidate")
    if value is None:
        return None
    candidate = _mapping(value, "compiler native_proof_candidate")
    certificate = candidate.get("certificate")
    if not isinstance(certificate, str) or not certificate.strip():
        raise CausalRuntimeBridgeError(
            "compiler native candidate lacks exact certificate bytes"
        )
    return certificate


@dataclass(frozen=True, slots=True)
class CompilerReferenceExposureV2:
    """One shared, measured compiler invocation and candidate/absence result."""

    compiler_record: StageRecord
    source_cid: str
    compiler_candidate: CausalProofCandidate | None
    semantic_protocol_cid: str = SEMANTIC_PROTOCOL_V2_CID
    causal_proof_protocol_cid: str = CAUSAL_PROOF_PROTOCOL_V2_CID
    schema: str = COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2:
            raise CausalRuntimeBridgeError(
                "unsupported compiler-reference exposure schema"
            )
        if (
            self.semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID
            or self.causal_proof_protocol_cid
            != CAUSAL_PROOF_PROTOCOL_V2_CID
        ):
            raise CausalRuntimeBridgeError(
                "compiler exposure protocol identity drifted"
            )
        try:
            source_cid = validate_cid(
                self.source_cid, codecs=("raw",)
            )
        except (TypeError, ValueError) as exc:
            raise CausalRuntimeBridgeError(
                "compiler exposure source CID is invalid"
            ) from exc
        object.__setattr__(self, "source_cid", source_cid)
        record = self.compiler_record
        if (
            not isinstance(record, StageRecord)
            or record.stage is not StageName.COMPILER
            or record.status is not StageStatus.SUCCESS
            or record.variant_id != "A0"
            or record.split not in {Split.PILOT, Split.DEVELOPMENT}
            or record.provenance.environment_sha256 is None
            or record.provenance.effective_identity.get("graph_invoked")
            is not True
        ):
            raise CausalRuntimeBridgeError(
                "shared compiler exposure requires an invoked A0 compiler "
                "StageRecord in pilot/development"
            )
        for identity in (
            record.provenance.requested_identity,
            record.provenance.effective_identity,
        ):
            if (
                identity.get("semantic_protocol_cid")
                != SEMANTIC_PROTOCOL_V2_CID
                or identity.get("source_cid") != source_cid
                or identity.get("proof_context_cid") is not None
            ):
                raise CausalRuntimeBridgeError(
                    "compiler exposure is not source-only semantic evidence"
                )
        if record.provenance.requested_identity != (
            _semantic_requested_identity(
                "A0",
                StageName.COMPILER,
                source_cid,
            )
        ):
            raise CausalRuntimeBridgeError(
                "compiler exposure requested identity differs from the "
                "frozen A0 compiler treatment"
            )
        certificate = _compiler_record_certificate(record)
        candidate = self.compiler_candidate
        if candidate is None:
            if certificate is not None:
                raise CausalRuntimeBridgeError(
                    "compiler exposure hides an emitted native candidate"
                )
            return
        if (
            not isinstance(candidate, CausalProofCandidate)
            or candidate.source != StageName.COMPILER.value
            or not isinstance(candidate.certificate, bytes)
            or candidate.certificate.decode("utf-8") != certificate
        ):
            raise CausalRuntimeBridgeError(
                "compiler candidate differs from the exposed compiler bytes"
            )
        artifact = self.artifact
        expected_cid = _artifact_cid(artifact)
        if candidate.artifact_cid != expected_cid:
            raise CausalRuntimeBridgeError(
                "compiler candidate artifact CID differs from the exposed "
                "canonical artifact bytes"
            )

    @classmethod
    def from_compiler_record(
        cls,
        compiler_record: StageRecord,
        *,
        source_text: str,
    ) -> Self:
        """Build the shared exposure without duplicating CID byte rules.

        The compiler StageRecord is the measured authority for both candidate
        presence and absence.  This constructor derives the raw artifact CID
        from the exact legacy-canonical ``StageArtifact`` bytes, so callers do
        not need to reproduce the compatibility encoding themselves.
        """

        if not isinstance(source_text, str) or not source_text.strip():
            raise CausalRuntimeBridgeError(
                "compiler exposure source text must be nonempty"
            )
        if not isinstance(compiler_record, StageRecord):
            raise CausalRuntimeBridgeError(
                "compiler exposure requires a compiler StageRecord"
            )
        if compiler_record.provenance.input_sha256 != (
            _legacy_source_input_sha256(source_text)
        ):
            raise CausalRuntimeBridgeError(
                "compiler exposure legacy input digest differs from its "
                "exact source bytes"
            )
        artifact = _stage_artifact(
            compiler_record,
            invocation_index=0,
            policy_reason="shared_g210_compiler_reference",
        )
        certificate = _compiler_record_certificate(compiler_record)
        candidate = (
            None
            if certificate is None
            else CausalProofCandidate(
                source=StageName.COMPILER.value,
                certificate=certificate,
                artifact_cid=_artifact_cid(artifact),
            )
        )
        return cls(
            compiler_record=compiler_record,
            source_cid=cid_for_bytes(source_text.encode("utf-8")),
            compiler_candidate=candidate,
        )

    @property
    def artifact(self) -> StageArtifact:
        return _stage_artifact(
            self.compiler_record,
            invocation_index=0,
            policy_reason="shared_g210_compiler_reference",
        )

    def identity_body(self) -> dict[str, object]:
        artifact = self.artifact
        body = {
            "schema": self.schema,
            "semantic_protocol_cid": self.semantic_protocol_cid,
            "causal_proof_protocol_cid": self.causal_proof_protocol_cid,
            "source_cid": self.source_cid,
            "run_id": self.compiler_record.run_id,
            "case_id": self.compiler_record.case_id,
            "cache_mode": self.compiler_record.cache_mode.value,
            "environment_sha256": (
                self.compiler_record.provenance.environment_sha256
            ),
            "compiler_invoked": True,
            "candidate_state": (
                "absent"
                if self.compiler_candidate is None
                else "present"
            ),
            "compiler_record": self.compiler_record.to_dict(),
            "compiler_record_cid": cid_for_dag_json(
                _plain(self.compiler_record.to_dict())
            ),
            "compiler_artifact": artifact.to_dict(),
            "compiler_artifact_cid": _artifact_cid(artifact),
            "compiler_artifact_sha256": _artifact_sha256(artifact),
            "compiler_candidate": _candidate_to_dict(
                self.compiler_candidate
            ),
        }
        plain = _plain(body)
        if not isinstance(plain, dict):  # pragma: no cover - fixed body shape
            raise CausalRuntimeBridgeError(
                "compiler exposure body is not a DAG-JSON object"
            )
        return plain

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_body())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_body(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "compiler_reference_exposure")
        expected = {
            "schema",
            "semantic_protocol_cid",
            "causal_proof_protocol_cid",
            "source_cid",
            "run_id",
            "case_id",
            "cache_mode",
            "environment_sha256",
            "compiler_invoked",
            "candidate_state",
            "compiler_record",
            "compiler_record_cid",
            "compiler_artifact",
            "compiler_artifact_cid",
            "compiler_artifact_sha256",
            "compiler_candidate",
            "receipt_cid",
        }
        _exact(data, expected, "compiler_reference_exposure")
        try:
            record = StageRecord.from_dict(data["compiler_record"])
            candidate = _candidate_from_dict(data["compiler_candidate"])
        except (ProtocolContractError, RuntimeBindingError) as exc:
            raise CausalRuntimeBridgeError(
                "compiler exposure contains invalid typed evidence"
            ) from exc
        result = cls(
            compiler_record=record,
            source_cid=str(data["source_cid"]),
            compiler_candidate=candidate,
            semantic_protocol_cid=str(data["semantic_protocol_cid"]),
            causal_proof_protocol_cid=str(
                data["causal_proof_protocol_cid"]
            ),
            schema=str(data["schema"]),
        )
        if _plain(data) != result.to_dict():
            raise CausalRuntimeBridgeError(
                "compiler exposure fields, artifact bytes, or CID changed"
            )
        return result


def _semantic_frontend(
    result: CaseResultRecord,
    *,
    source_text: str,
) -> tuple[StageRecord, ...]:
    if not isinstance(result, CaseResultRecord):
        raise CausalRuntimeBridgeError(
            "semantic_result must be a CaseResultRecord"
        )
    try:
        restored = CaseResultRecord.from_dict(result.to_dict())
    except ProtocolContractError as exc:
        raise CausalRuntimeBridgeError(
            "semantic result failed canonical replay"
        ) from exc
    if restored != result or result.split is Split.HOLDOUT:
        raise CausalRuntimeBridgeError(
            "G210 requires a canonical non-holdout semantic result"
        )
    source_cid = cid_for_bytes(source_text.encode("utf-8"))
    profile = get_causal_proof_variant_profile(result.variant_id)
    expected = tuple(
        stage
        for stage in profile.effective_stages
        if stage in _FRONTEND_STAGES
    )
    records = tuple(
        stage for stage in result.stages if stage.stage in _FRONTEND_STAGES
    )
    if tuple(stage.stage for stage in records) != expected:
        raise CausalRuntimeBridgeError(
            "semantic result does not contain the exact G210 frontend prefix"
        )
    expected_input_sha256 = _legacy_source_input_sha256(source_text)
    expected_upstream: tuple[str, ...] = ()
    for stage in records:
        if (
            stage.provenance.input_sha256 != expected_input_sha256
            or stage.provenance.upstream_stage_digests != expected_upstream
        ):
            raise CausalRuntimeBridgeError(
                "immutable semantic frontend has a source-input or digest-chain "
                "mismatch"
            )
        if stage.provenance.requested_identity != (
            _semantic_requested_identity(
                result.variant_id,
                stage.stage,
                source_cid,
            )
        ):
            raise CausalRuntimeBridgeError(
                f"{stage.stage.value} requested identity differs from the "
                "frozen semantic treatment"
            )
        for identity in (
            stage.provenance.requested_identity,
            stage.provenance.effective_identity,
        ):
            if (
                identity.get("semantic_protocol_cid")
                != SEMANTIC_PROTOCOL_V2_CID
                or identity.get("source_cid") != source_cid
                or identity.get("proof_context_cid") is not None
            ):
                raise CausalRuntimeBridgeError(
                    f"{stage.stage.value} semantic evidence received proof "
                    "context or changed source identity"
                )
        expected_upstream = (*expected_upstream, stage.digest)
    return records


def _runtime_identity(
    variant_id: str,
    stage: StageName,
    exposure_cid: str,
) -> dict[str, object]:
    definition = get_variant_definition(variant_id)
    if stage in definition.stages:
        identity = dict(definition.requested_identity(stage))
    else:
        identity = {
            "variant_id": variant_id,
            "configuration_sha256": definition.digest,
        }
    identity.update(
        {
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "causal_variant_profile_cid": (
                CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
            ),
            "compiler_reference_exposure_cid": exposure_cid,
        }
    )
    return identity


def _proof_requested_identity(
    variant_id: str,
    stage: StageName,
    *,
    source_cid: str,
    proof_context_cid: str,
    exposure_cid: str,
) -> dict[str, object]:
    """Rebuild one exact G210 proof-stage requested identity."""

    identity = _runtime_identity(variant_id, stage, exposure_cid)
    identity.update(
        {
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": source_cid,
            "proof_context_cid": proof_context_cid,
        }
    )
    return identity


def _terminal_kernel_target_identity(
    selection_result: CausalProofGraphResult,
) -> dict[str, object]:
    """Derive the terminal kernel target from the ordered native sidecars."""

    sidecars = selection_result.receipt.get("kernel_receipts")
    if not isinstance(sidecars, Sequence) or isinstance(
        sidecars, (str, bytes, bytearray)
    ):
        raise CausalRuntimeBridgeError(
            "selection kernel receipts must be an array"
        )
    if not sidecars:
        return {}
    terminal = _mapping(sidecars[-1], "terminal kernel sidecar")
    candidate_cid = validate_cid(
        terminal.get("candidate_cid"),
        codecs=("raw",),
    )
    receipt_cid = validate_cid(
        terminal.get("receipt_cid"),
        codecs=("dag-json",),
    )
    compiler = _mapping(
        selection_result.receipt.get("compiler_reference"),
        "selection compiler reference",
    )
    source: object
    artifact_cid: object
    if (
        compiler.get("candidate_cid") == candidate_cid
        and compiler.get("kernel_receipt_cid") == receipt_cid
    ):
        source = StageName.COMPILER.value
        artifact_cid = compiler.get("artifact_cid")
    else:
        optional = selection_result.receipt.get("optional_candidates")
        if not isinstance(optional, Sequence) or isinstance(
            optional, (str, bytes, bytearray)
        ):
            raise CausalRuntimeBridgeError(
                "selection optional candidates must be an array"
            )
        matches = [
            _mapping(item, "selection optional candidate")
            for item in optional
            if isinstance(item, Mapping)
            and item.get("candidate_cid") == candidate_cid
            and item.get("kernel_receipt_cid") == receipt_cid
            and item.get("kernel_checked") is True
        ]
        if len(matches) != 1:
            raise CausalRuntimeBridgeError(
                "terminal kernel target has no unique selected producer"
            )
        source = matches[0].get("source")
        artifact_cid = matches[0].get("artifact_cid")
    if source not in {
        StageName.COMPILER.value,
        StageName.HAMMER.value,
        StageName.LEANSTRAL.value,
    }:
        raise CausalRuntimeBridgeError(
            "terminal kernel target source is invalid"
        )
    validated_artifact_cid = validate_cid(
        artifact_cid,
        codecs=("raw",),
    )
    return {
        "causal_target_candidate_source": source,
        "causal_target_candidate_cid": candidate_cid,
        "causal_target_candidate_artifact_cid": validated_artifact_cid,
        "causal_target_candidate_artifact_sha256": sha256_digest_for_cid(
            validated_artifact_cid,
            codecs=("raw",),
        ),
    }


def _artifact_from_invocation(
    stage: StageName,
    invocation: StageInvocation,
    *,
    invocation_index: int,
    policy_reason: str,
) -> StageArtifact:
    output = invocation.output
    return StageArtifact(
        stage=stage,
        status=output.status,
        data=_plain(output.data),
        output_sha256=None,
        effective_identity=_plain(
            output.effective_identity
        ),  # type: ignore[arg-type]
        invocation_index=invocation_index,
        invoked=True,
        policy_reason=policy_reason,
    )


def _proof_failure(
    stage: StageName,
    output: StageOutput,
) -> CausalProofFailure:
    if stage is StageName.HAMMER:
        if output.failure_code is FailureCode.PREMISE_SELECTION_MISS:
            code = "hammer_premise_selection_miss"
        elif output.failure_code is (
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
        ):
            code = "hammer_timeout"
        elif output.failure_code in {
            FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
            FailureCode.FIXTURE_INVALID,
        }:
            code = "hammer_schema_invalid"
        elif output.status is StageStatus.SUCCESS:
            code = "hammer_candidate_absent"
        else:
            code = "hammer_solver_failure"
        assert code in CAUSAL_PROOF_HAMMER_FAILURE_CODES_V2
        return CausalProofFailure("hammer", code, output.failure_detail or "")

    data = output.data if isinstance(output.data, Mapping) else {}
    safe_class = data.get("safe_failure_class")
    if output.status is StageStatus.SUCCESS or safe_class not in {
        "length_exhausted",
        "malformed_request",
        "malformed_response",
        "inadmissible_proposal",
        "provider_error",
        "unavailable",
        "timed_out",
        "resource_exhausted",
    }:
        raise CausalRuntimeBridgeError(
            "Leanstral failure lacks a replayable typed failed-stage receipt"
        )
    if safe_class == "length_exhausted":
        code = "leanstral_output_limit"
    elif safe_class == "timed_out":
        code = "leanstral_timeout"
    elif safe_class == "inadmissible_proposal":
        code = "leanstral_forbidden_construct"
    elif safe_class in {"malformed_request", "malformed_response"}:
        code = "leanstral_schema_invalid"
    else:
        code = "leanstral_provider_failure"
    return CausalProofFailure(
        "leanstral", code, output.failure_detail or ""
    )


def _certificate_from_output(
    stage: StageName,
    output: StageOutput,
) -> str | None:
    if output.status is not StageStatus.SUCCESS:
        return None
    data = _mapping(output.data, f"{stage.value} output")
    if stage is StageName.HAMMER:
        value = data.get("proof_text", data.get("certificate"))
    else:
        draft = data.get("draft")
        value = (
            draft.get("proof_text")
            if isinstance(draft, Mapping)
            else data.get("certificate")
        )
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CausalRuntimeBridgeError(
            f"{stage.value} emitted invalid candidate bytes"
        )
    return value


def _aggregate_kernel_telemetry(
    invocations: Sequence[StageInvocation],
) -> TelemetryRecord:
    if not invocations:
        raise CausalRuntimeBridgeError(
            "terminal kernel evidence requires an invocation"
        )
    return _aggregate_kernel_telemetry_records(
        tuple(item.telemetry for item in invocations)
    )


def _aggregate_kernel_telemetry_records(
    values: Sequence[TelemetryRecord],
) -> TelemetryRecord:
    if not values:
        raise CausalRuntimeBridgeError(
            "terminal kernel evidence requires telemetry"
        )
    return TelemetryRecord(
        wall_time_ms=sum(item.wall_time_ms for item in values),
        cpu_time_ms=sum(item.cpu_time_ms for item in values),
        peak_memory_bytes=max(item.peak_memory_bytes for item in values),
        input_items=sum(item.input_items for item in values),
        output_items=sum(item.output_items for item in values),
        model_calls=sum(item.model_calls for item in values),
        cache_hits=sum(item.cache_hits for item in values),
        cache_misses=sum(item.cache_misses for item in values),
        retries=sum(item.retries for item in values),
        bytes_in=sum(item.bytes_in for item in values),
        bytes_out=sum(item.bytes_out for item in values),
        resource_lane=ResourceLane.KERNEL,
    )


@dataclass(frozen=True, slots=True)
class CausalRuntimeEvidenceV2:
    """Persistable selection, CaseResult, telemetry, and compiler exposure."""

    compiler_exposure: CompilerReferenceExposureV2
    semantic_frontend: tuple[StageRecord, ...]
    selection_result: CausalProofGraphResult
    case_result: CaseResultRecord
    causal_case_receipt: Mapping[str, object]
    kernel_check_telemetry: tuple[Mapping[str, object], ...]
    source_text: str
    proof_context: Mapping[str, object]
    proof_context_cid: str
    schema: str = CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2:
            raise CausalRuntimeBridgeError(
                "unsupported causal runtime evidence schema"
            )
        if (
            not isinstance(
                self.compiler_exposure,
                CompilerReferenceExposureV2,
            )
            or not isinstance(self.semantic_frontend, tuple)
            or not all(
                isinstance(item, StageRecord)
                for item in self.semantic_frontend
            )
            or not isinstance(
                self.selection_result,
                CausalProofGraphResult,
            )
            or not isinstance(self.case_result, CaseResultRecord)
            or not isinstance(self.causal_case_receipt, Mapping)
            or not isinstance(self.kernel_check_telemetry, tuple)
            or not all(
                isinstance(item, Mapping)
                for item in self.kernel_check_telemetry
            )
            or not isinstance(self.source_text, str)
            or not self.source_text.strip()
            or not isinstance(self.proof_context, Mapping)
        ):
            raise CausalRuntimeBridgeError(
                "causal runtime evidence contains invalid typed fields"
            )
        frozen_context = _freeze_plain_json(self.proof_context)
        frozen_case_receipt = _freeze_plain_json(
            self.causal_case_receipt
        )
        frozen_telemetry = tuple(
            _freeze_plain_json(item)
            for item in self.kernel_check_telemetry
        )
        if (
            not isinstance(frozen_context, Mapping)
            or not isinstance(frozen_case_receipt, Mapping)
            or not all(
                isinstance(item, Mapping)
                for item in frozen_telemetry
            )
        ):  # pragma: no cover - guarded by input shapes
            raise CausalRuntimeBridgeError(
                "causal runtime JSON fields did not remain objects"
            )
        try:
            proof_context_cid = validate_cid(
                self.proof_context_cid,
                codecs=("dag-json",),
            )
        except (TypeError, ValueError) as exc:
            raise CausalRuntimeBridgeError(
                "causal runtime proof-context CID is invalid"
            ) from exc
        if (
            proof_context_cid
            != cid_for_dag_json(_plain(frozen_context))
            or self.compiler_exposure.source_cid
            != cid_for_bytes(self.source_text.encode("utf-8"))
        ):
            raise CausalRuntimeBridgeError(
                "causal runtime source or proof-context identity changed"
            )
        object.__setattr__(self, "proof_context", frozen_context)
        object.__setattr__(
            self,
            "causal_case_receipt",
            frozen_case_receipt,
        )
        object.__setattr__(
            self,
            "kernel_check_telemetry",
            frozen_telemetry,
        )
        object.__setattr__(
            self,
            "proof_context_cid",
            proof_context_cid,
        )

    def identity_body(self) -> dict[str, object]:
        frontend = [
            _plain(item.to_dict()) for item in self.semantic_frontend
        ]
        case_result = _plain(self.case_result.to_dict())
        body = {
            "schema": self.schema,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "source_cid": self.compiler_exposure.source_cid,
            "source_text_utf8": self.source_text,
            "proof_context": _plain(self.proof_context),
            "proof_context_cid": self.proof_context_cid,
            "compiler_reference_exposure": (
                self.compiler_exposure.to_dict()
            ),
            "compiler_reference_exposure_cid": (
                self.compiler_exposure.receipt_cid
            ),
            "semantic_frontend": frontend,
            "semantic_frontend_cid": cid_for_dag_json(frontend),
            "selection_receipt": dict(self.selection_result.receipt),
            "selection_receipt_cid": self.selection_result.receipt_cid,
            "case_result": case_result,
            "case_result_cid": cid_for_dag_json(case_result),
            "causal_case_receipt": _plain(self.causal_case_receipt),
            "kernel_check_telemetry": [
                _plain(item) for item in self.kernel_check_telemetry
            ],
        }
        plain = _plain(body)
        if not isinstance(plain, dict):  # pragma: no cover - fixed body shape
            raise CausalRuntimeBridgeError(
                "causal runtime body is not a DAG-JSON object"
            )
        return plain

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_body())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_body(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        return validate_causal_runtime_evidence_v2(value)


def _proof_artifact_binding(
    *,
    stage: StageName,
    record: StageRecord,
    selection_record: Mapping[str, object],
) -> tuple[StageArtifact, str | None]:
    invocation_index = record.provenance.effective_identity.get(
        "graph_invocation_index"
    )
    if (
        isinstance(invocation_index, bool)
        or not isinstance(invocation_index, int)
    ):
        raise CausalRuntimeBridgeError(
            f"{stage.value} record lacks its invocation index"
        )
    artifact = _stage_artifact(
        record,
        invocation_index=invocation_index,
        policy_reason="g210_optional_trigger",
    )
    output = StageOutput(
        data=_plain(record.data),
        status=record.status,
        effective_identity=_plain(
            record.provenance.effective_identity
        ),  # type: ignore[arg-type]
        failure_code=record.failure_code,
        failure_detail=record.failure_detail,
    )
    certificate = _certificate_from_output(stage, output)
    if certificate is None:
        failure = _proof_failure(stage, output)
        if (
            selection_record.get("candidate_cid") is not None
            or selection_record.get("artifact_cid") is not None
            or selection_record.get("failure_code")
            != failure.failure_code
        ):
            raise CausalRuntimeBridgeError(
                f"{stage.value} selection differs from its typed failure "
                "StageRecord"
            )
        return artifact, None
    artifact_cid = _artifact_cid(artifact)
    if selection_record.get("artifact_cid") != artifact_cid:
        raise CausalRuntimeBridgeError(
            f"{stage.value} selection artifact CID changed"
        )
    candidate_cid = cid_for_bytes(certificate.encode("utf-8"))
    if selection_record.get("candidate_cid") != candidate_cid:
        raise CausalRuntimeBridgeError(
            f"{stage.value} candidate CID differs from exact artifact bytes"
        )
    return artifact, certificate


def validate_causal_runtime_evidence_v2(
    value: object,
) -> CausalRuntimeEvidenceV2:
    """Replay persisted G210 evidence, including every native receipt."""

    data = _mapping(value, "causal_runtime_evidence")
    expected = {
        "schema",
        "semantic_protocol_cid",
        "causal_proof_protocol_cid",
        "source_cid",
        "source_text_utf8",
        "proof_context",
        "proof_context_cid",
        "compiler_reference_exposure",
        "compiler_reference_exposure_cid",
        "semantic_frontend",
        "semantic_frontend_cid",
        "selection_receipt",
        "selection_receipt_cid",
        "case_result",
        "case_result_cid",
        "causal_case_receipt",
        "kernel_check_telemetry",
        "receipt_cid",
    }
    _exact(data, expected, "causal_runtime_evidence")
    if (
        data["schema"] != CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2
        or data["semantic_protocol_cid"] != SEMANTIC_PROTOCOL_V2_CID
        or data["causal_proof_protocol_cid"]
        != CAUSAL_PROOF_PROTOCOL_V2_CID
    ):
        raise CausalRuntimeBridgeError(
            "causal runtime evidence protocol drifted"
        )
    source_text = data["source_text_utf8"]
    if not isinstance(source_text, str) or not source_text.strip():
        raise CausalRuntimeBridgeError(
            "causal runtime evidence lacks exact source UTF-8 text"
        )
    proof_context = _mapping(
        data["proof_context"], "causal runtime proof_context"
    )
    expected_source_cid = cid_for_bytes(source_text.encode("utf-8"))
    expected_proof_context_cid = cid_for_dag_json(
        _plain(proof_context)
    )
    if (
        data["source_cid"] != expected_source_cid
        or data["proof_context_cid"] != expected_proof_context_cid
    ):
        raise CausalRuntimeBridgeError(
            "causal runtime exact source/proof-context bytes changed"
        )
    try:
        exposure = CompilerReferenceExposureV2.from_dict(
            data["compiler_reference_exposure"]
        )
        raw_frontend = data["semantic_frontend"]
        if not isinstance(raw_frontend, list):
            raise CausalRuntimeBridgeError(
                "semantic_frontend must be an array"
            )
        frontend = tuple(
            StageRecord.from_dict(item) for item in raw_frontend
        )
        selection = validate_causal_proof_selection_receipt(
            data["selection_receipt"]
        )
        selection_result = CausalProofGraphResult(
            receipt=selection,
            receipt_cid=str(data["selection_receipt_cid"]),
        )
        case_result = CaseResultRecord.from_dict(data["case_result"])
        causal_receipt = validate_causal_rescue_case_receipt(
            data["causal_case_receipt"]
        )
    except (
        ProtocolContractError,
        RuntimeBindingError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(exc, CausalRuntimeBridgeError):
            raise
        raise CausalRuntimeBridgeError(
            "causal runtime typed evidence failed replay"
        ) from exc
    if (
        data["source_cid"] != exposure.source_cid
        or data["compiler_reference_exposure_cid"]
        != exposure.receipt_cid
        or data["semantic_frontend_cid"]
        != cid_for_dag_json(
            _plain([item.to_dict() for item in frontend])
        )
        or data["case_result_cid"]
        != cid_for_dag_json(_plain(case_result.to_dict()))
        or tuple(case_result.stages[: len(frontend)]) != frontend
        or _plain(causal_receipt)
        != _plain(
            build_causal_rescue_case_receipt(
                case_result, selection_result.receipt
            )
        )
    ):
        raise CausalRuntimeBridgeError(
            "causal runtime evidence lost an immutable evidence binding"
        )
    expected_proof_input = {
        "text": source_text,
        **_plain(proof_context),  # type: ignore[arg-type]
    }
    try:
        compiled = compile_reviewed_obligation(expected_proof_input)
    except RuntimeBindingError as exc:
        raise CausalRuntimeBridgeError(
            "persisted proof context no longer compiles"
        ) from exc
    if compiled is None:
        raise CausalRuntimeBridgeError(
            "G210 evidence lacks a reviewed compiled obligation"
        )
    proof_compiler_artifact, proof_compiler_candidate = (
        _proof_compiler_binding(
            exposure,
            source_text=source_text,
            proof_context=proof_context,
        )
    )
    semantic_artifacts: list[StageArtifact] = [proof_compiler_artifact]
    for record in frontend:
        if record.stage is StageName.COMPILER:
            continue
        semantic_artifacts.append(
            _stage_artifact(
                record,
                invocation_index=len(semantic_artifacts),
                policy_reason="immutable_g200_semantic_frontend",
            )
        )
    try:
        semantic_request = StageRequest(
            run_id=case_result.run_id,
            case_id=case_result.case_id,
            case_manifest_sha256=case_result.case_manifest_sha256,
            variant_id=case_result.variant_id,
            split=case_result.split,
            cache_mode=case_result.cache_mode,
            input_data={"text": source_text},
            requested_identity={},
            environment_sha256=(
                case_result.stages[0].provenance.environment_sha256
            ),
            upstream_artifacts=tuple(semantic_artifacts),
            source=("causal_runtime_v2_replay",),
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
            proof_context=proof_context,
        )
        semantic_binding = semantic_context_binding(
            kernel_input_semantic_context(semantic_request)
        )
        context_cid = validate_cid(
            semantic_binding.get("context_cid"),
            codecs=("dag-json",),
        )
        artifact_cids = semantic_binding.get("artifact_cids")
        if not isinstance(artifact_cids, list):
            raise ValueError("semantic artifact CIDs are not an array")
        expected_native_semantic_fields = {
            "semantic_context_sha256": sha256_digest_for_cid(
                context_cid, codecs=("dag-json",)
            ),
            "semantic_artifact_sha256s": [
                sha256_digest_for_cid(value, codecs=("dag-json",))
                for value in artifact_cids
            ],
        }
    except (ProtocolContractError, RuntimeBindingError, TypeError, ValueError) as exc:
        raise CausalRuntimeBridgeError(
            "persisted semantic context cannot be independently rebuilt"
        ) from exc
    if (
        exposure.compiler_record.run_id != case_result.run_id
        or exposure.compiler_record.case_id != case_result.case_id
        or exposure.compiler_record.split is not case_result.split
        or exposure.compiler_record.cache_mode is not case_result.cache_mode
        or exposure.compiler_record.case_manifest_sha256
        != case_result.case_manifest_sha256
        or exposure.compiler_record.provenance.environment_sha256
        != case_result.stages[0].provenance.environment_sha256
        or exposure.compiler_record.provenance.input_sha256
        != _legacy_source_input_sha256(source_text)
    ):
        raise CausalRuntimeBridgeError(
            "compiler exposure differs from its CaseResult coordinate"
        )
    expected_frontend_stages = tuple(
        stage.stage
        for stage in _semantic_frontend(
            CaseResultRecord.from_stages(frontend),
            source_text=source_text,
        )
    )
    if expected_frontend_stages != tuple(
        stage.stage for stage in frontend
    ):
        raise CausalRuntimeBridgeError(
            "persisted semantic frontend changed during replay"
        )
    proof_identity = {
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "causal_variant_profile_cid": (
            CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
        ),
        "compiler_reference_exposure_cid": exposure.receipt_cid,
    }
    terminal_kernel_requested_identity = _proof_requested_identity(
        case_result.variant_id,
        StageName.KERNEL,
        source_cid=expected_source_cid,
        proof_context_cid=expected_proof_context_cid,
        exposure_cid=exposure.receipt_cid,
    )
    terminal_kernel_requested_identity.update(
        _terminal_kernel_target_identity(selection_result)
    )
    for stage in case_result.stages:
        proof_stage = stage.stage not in _FRONTEND_STAGES
        expected_proof_cid = (
            None
            if not proof_stage
            else expected_proof_context_cid
        )
        expected_requested_identity = (
            _semantic_requested_identity(
                case_result.variant_id,
                stage.stage,
                expected_source_cid,
            )
            if not proof_stage
            else (
                terminal_kernel_requested_identity
                if stage.stage is StageName.KERNEL
                else _proof_requested_identity(
                    case_result.variant_id,
                    stage.stage,
                    source_cid=expected_source_cid,
                    proof_context_cid=expected_proof_context_cid,
                    exposure_cid=exposure.receipt_cid,
                )
            )
        )
        if (
            stage.provenance.requested_identity
            != expected_requested_identity
        ):
            raise CausalRuntimeBridgeError(
                f"{stage.stage.value} requested identity differs from the "
                "frozen causal treatment"
            )
        for identity_name, identity in (
            ("requested", stage.provenance.requested_identity),
            ("effective", stage.provenance.effective_identity),
        ):
            if (
                identity.get("semantic_protocol_cid")
                != SEMANTIC_PROTOCOL_V2_CID
                or identity.get("source_cid") != expected_source_cid
                or identity.get("proof_context_cid")
                != expected_proof_cid
                or (
                    proof_stage
                    and any(
                        identity.get(field) != expected
                        for field, expected in proof_identity.items()
                    )
                )
                or (
                    not proof_stage
                    and any(field in identity for field in proof_identity)
                )
            ):
                raise CausalRuntimeBridgeError(
                    f"{stage.stage.value} {identity_name} identity crossed "
                    "the semantic/proof boundary"
                )
        if stage.stage is StageName.KERNEL:
            kernel_identity = stage.provenance.effective_identity
            raw_kernel_telemetry = data["kernel_check_telemetry"]
            if (
                kernel_identity.get("causal_selection_receipt_cid")
                != selection_result.receipt_cid
                or not isinstance(raw_kernel_telemetry, list)
                or type(kernel_identity.get("kernel_check_count")) is not int
                or kernel_identity.get("kernel_check_count")
                != len(raw_kernel_telemetry)
            ):
                raise CausalRuntimeBridgeError(
                    "terminal kernel identity differs from its causal "
                    "selection or native-check count"
                )
    if (
        selection_result.receipt.get("source_cid")
        != exposure.source_cid
        or selection_result.receipt.get("run_id") != case_result.run_id
        or selection_result.receipt.get("case_id") != case_result.case_id
        or selection_result.receipt.get("variant_id")
        != case_result.variant_id
    ):
        raise CausalRuntimeBridgeError(
            "causal selection differs from its terminal CaseResult"
        )
    compiler = _mapping(
        selection_result.receipt["compiler_reference"],
        "selection compiler reference",
    )
    candidate = proof_compiler_candidate
    if (
        compiler.get("candidate_cid")
        != (None if candidate is None else candidate.candidate_cid)
        or compiler.get("artifact_cid")
        != (None if candidate is None else candidate.artifact_cid)
    ):
        raise CausalRuntimeBridgeError(
            "selection used a different shared compiler reference"
        )
    candidate_bindings: dict[
        str, tuple[str, str, StageArtifact]
    ] = {}
    if candidate is not None:
        assert candidate.candidate_cid is not None
        compiler_artifact = proof_compiler_artifact
        if (
            candidate.artifact_cid != _artifact_cid(compiler_artifact)
            or _artifact_sha256(compiler_artifact)
            != compiler_artifact.digest
        ):
            raise CausalRuntimeBridgeError(
                "compiler candidate is not its exact canonical StageArtifact"
            )
        candidate_bindings[candidate.candidate_cid] = (
            StageName.COMPILER.value,
            candidate.certificate.decode("utf-8"),
            compiler_artifact,
        )
    optionals = selection_result.receipt.get("optional_candidates")
    if not isinstance(optionals, Sequence) or isinstance(
        optionals, (str, bytes, bytearray)
    ):
        raise CausalRuntimeBridgeError(
            "selection optional_candidates must be an array"
        )
    by_stage = {stage.stage: stage for stage in case_result.stages}
    for raw in optionals:
        item = _mapping(raw, "selection optional candidate")
        stage = StageName(str(item["source"]))
        record = by_stage.get(stage)
        if item.get("invoked") is True:
            if record is None:
                raise CausalRuntimeBridgeError(
                    f"invoked {stage.value} lacks durable telemetry"
                )
            artifact, certificate = _proof_artifact_binding(
                stage=stage,
                record=record,
                selection_record=item,
            )
            if certificate is not None:
                candidate_cid = str(item["candidate_cid"])
                if candidate_cid in candidate_bindings:
                    if (
                        item.get("overlap") is not True
                        or item.get("duplicate_of_candidate_cid")
                        != candidate_cid
                    ):
                        raise CausalRuntimeBridgeError(
                            "candidate bytes repeat without overlap binding"
                        )
                    # The producer StageRecord and its own artifact CID were
                    # replayed above.  A byte-identical candidate deliberately
                    # receives no second native check and retains the first
                    # candidate's authority, so it must not replace that
                    # candidate-to-sidecar binding.
                    continue
                candidate_bindings[candidate_cid] = (
                    stage.value,
                    certificate,
                    artifact,
                )
        elif record is not None:
            raise CausalRuntimeBridgeError(
                f"suppressed {stage.value} has an execution record"
            )
    raw_telemetry = data["kernel_check_telemetry"]
    if not isinstance(raw_telemetry, list) or not raw_telemetry:
        raise CausalRuntimeBridgeError(
            "kernel check telemetry must be a nonempty array"
        )
    sidecars = selection_result.receipt.get("kernel_receipts")
    if not isinstance(sidecars, Sequence) or isinstance(
        sidecars, (str, bytes, bytearray)
    ):
        raise CausalRuntimeBridgeError(
            "selection kernel_receipts must be an array"
        )
    sidecar_pairs = {
        (
            str(_mapping(item, "kernel sidecar")["candidate_cid"]),
            str(_mapping(item, "kernel sidecar")["receipt_cid"]),
        )
        for item in sidecars
    }
    if len(sidecar_pairs) != len(sidecars):
        raise CausalRuntimeBridgeError(
            "causal native sidecars repeat a candidate or receipt"
        )
    checked_candidate_cids: set[str] = set()
    for raw in sidecars:
        sidecar = _mapping(raw, "kernel sidecar")
        candidate_cid = str(sidecar.get("candidate_cid"))
        binding = candidate_bindings.get(candidate_cid)
        if binding is None or candidate_cid in checked_candidate_cids:
            raise CausalRuntimeBridgeError(
                "native sidecar lacks one exact producer StageArtifact"
            )
        checked_candidate_cids.add(candidate_cid)
        source, certificate, artifact = binding
        artifact_cid = _artifact_cid(artifact)
        artifact_sha256 = _artifact_sha256(artifact)
        receipt = _mapping(
            _plain(sidecar.get("receipt")),
            "native kernel sidecar receipt",
        )
        attempts = receipt.get("candidate_attempts")
        try:
            rendered_source_sha256 = hashlib.sha256(
                compiled.render(certificate).encode("utf-8")
            ).hexdigest()
        except RuntimeBindingError as exc:
            raise CausalRuntimeBridgeError(
                "persisted candidate cannot reconstruct its native source"
            ) from exc
        if (
            sidecar.get("candidate_bytes_utf8") != certificate
            or sidecar.get("candidate_bytes_length")
            != len(certificate.encode("utf-8"))
            or cid_for_bytes(certificate.encode("utf-8"))
            != candidate_cid
            or artifact_cid
            != (
                compiler.get("artifact_cid")
                if source == StageName.COMPILER.value
                else next(
                    item.get("artifact_cid")
                    for item in optionals
                    if item.get("source") == source
                    and item.get("candidate_cid") == candidate_cid
                )
            )
            or sha256_digest_for_cid(
                artifact_cid, codecs=("raw",)
            )
            != artifact_sha256
            or artifact_sha256 != artifact.digest
            or receipt.get("candidate_source") != source
            or receipt.get("candidate_artifact_sha256")
            != artifact_sha256
            or receipt.get("compiled_obligation_sha256")
            != compiled.digest
            or receipt.get("obligation_sha256")
            != compiled.obligation_sha256
            or receipt.get("source_sha256")
            != rendered_source_sha256
            or any(
                receipt.get(field) != expected
                for field, expected in expected_native_semantic_fields.items()
            )
            or not isinstance(attempts, list)
            or len(attempts) != 1
            or not isinstance(attempts[0], Mapping)
            or attempts[0].get("candidate_source") != source
            or attempts[0].get("candidate_artifact_sha256")
            != artifact_sha256
            or attempts[0].get("source_sha256")
            != rendered_source_sha256
        ):
            raise CausalRuntimeBridgeError(
                "native receipt does not replay one exact candidate source"
            )
    telemetry_maps: list[Mapping[str, object]] = []
    telemetry_records: list[TelemetryRecord] = []
    recorded_pairs: set[tuple[str, str]] = set()
    for raw in raw_telemetry:
        item = _mapping(raw, "kernel check telemetry")
        _exact(
            item,
            {"candidate_cid", "native_receipt_cid", "telemetry"},
            "kernel check telemetry",
        )
        telemetry = TelemetryRecord.from_dict(item["telemetry"])
        if telemetry.resource_lane is not ResourceLane.KERNEL:
            raise CausalRuntimeBridgeError(
                "kernel check telemetry uses the wrong resource lane"
            )
        receipt_cid = str(item["native_receipt_cid"])
        validate_cid(receipt_cid, codecs=("dag-json",))
        raw_candidate_cid = item["candidate_cid"]
        if raw_candidate_cid is not None:
            validate_cid(raw_candidate_cid, codecs=("raw",))
            recorded_pairs.add((str(raw_candidate_cid), receipt_cid))
        telemetry_records.append(telemetry)
        telemetry_maps.append(
            MappingProxyType(
                {
                    "candidate_cid": item["candidate_cid"],
                    "native_receipt_cid": receipt_cid,
                    "telemetry": telemetry.to_dict(),
                }
            )
        )
    kernel_record = by_stage.get(StageName.KERNEL)
    if kernel_record is None:
        raise CausalRuntimeBridgeError(
            "causal runtime evidence lacks its terminal kernel record"
        )
    terminal_receipt_cid = cid_for_dag_json(_plain(kernel_record.data))
    terminal_receipt = _mapping(
        kernel_record.data, "terminal native-kernel receipt"
    )
    if any(
        _plain(terminal_receipt.get(field)) != expected
        for field, expected in expected_native_semantic_fields.items()
    ):
        raise CausalRuntimeBridgeError(
            "terminal native receipt differs from the rebuilt semantic "
            "context CIDs"
        )
    if sidecars:
        if (
            recorded_pairs != sidecar_pairs
            or len(recorded_pairs) != len(telemetry_maps)
        ):
            raise CausalRuntimeBridgeError(
                "persisted telemetry does not cover every native check once"
            )
    elif (
        len(telemetry_maps) != 1
        or telemetry_maps[0]["candidate_cid"] is not None
        or telemetry_maps[0]["native_receipt_cid"]
        != terminal_receipt_cid
    ):
        raise CausalRuntimeBridgeError(
            "candidate-absent path lacks one measured negative kernel check"
        )
    if (
        _aggregate_kernel_telemetry_records(telemetry_records)
        != kernel_record.telemetry
    ):
        raise CausalRuntimeBridgeError(
            "terminal kernel telemetry differs from its per-check receipts"
        )
    body = {key: _plain(item) for key, item in data.items() if key != "receipt_cid"}
    if data["receipt_cid"] != cid_for_dag_json(body):
        raise CausalRuntimeBridgeError(
            "causal runtime evidence CID changed"
        )
    return CausalRuntimeEvidenceV2(
        compiler_exposure=exposure,
        semantic_frontend=frontend,
        selection_result=selection_result,
        case_result=case_result,
        causal_case_receipt=MappingProxyType(dict(causal_receipt)),
        kernel_check_telemetry=tuple(telemetry_maps),
        source_text=source_text,
        proof_context=MappingProxyType(dict(proof_context)),
        proof_context_cid=str(data["proof_context_cid"]),
    )


def execute_causal_runtime_case_v2(
    semantic_result: CaseResultRecord,
    source_text: str,
    proof_context: Mapping[str, object],
    compiler_exposure: CompilerReferenceExposureV2,
    adapters: Mapping[StageName, StageAdapter],
) -> CausalRuntimeEvidenceV2:
    """Execute one G210 case with lazy proof adapters and native receipts."""

    if not isinstance(source_text, str) or not source_text.strip():
        raise CausalRuntimeBridgeError(
            "causal runtime source text must be nonempty"
        )
    frontend = _semantic_frontend(
        semantic_result, source_text=source_text
    )
    source_cid = cid_for_bytes(source_text.encode("utf-8"))
    if (
        not isinstance(compiler_exposure, CompilerReferenceExposureV2)
        or compiler_exposure.source_cid != source_cid
        or compiler_exposure.compiler_record.run_id
        != semantic_result.run_id
        or compiler_exposure.compiler_record.case_id
        != semantic_result.case_id
        or compiler_exposure.compiler_record.cache_mode
        is not semantic_result.cache_mode
        or compiler_exposure.compiler_record.split
        is not semantic_result.split
        or compiler_exposure.compiler_record.case_manifest_sha256
        != semantic_result.case_manifest_sha256
        or compiler_exposure.compiler_record.provenance.environment_sha256
        != frontend[0].provenance.environment_sha256
        or compiler_exposure.compiler_record.provenance.input_sha256
        != _legacy_source_input_sha256(source_text)
    ):
        raise CausalRuntimeBridgeError(
            "compiler exposure differs from the semantic case/cache coordinate"
        )
    profile = get_causal_proof_variant_profile(
        semantic_result.variant_id
    )
    expected_adapters = {
        *profile.optional_order,
        StageName.KERNEL,
    }
    full_live_route = set(profile.effective_stages)
    supplied_adapters = set(adapters) if isinstance(adapters, Mapping) else set()
    if (
        not isinstance(adapters, Mapping)
        or (
            supplied_adapters != expected_adapters
            and supplied_adapters != full_live_route
        )
        or any(
            not isinstance(adapter, StageAdapter)
            or adapter.stage is not stage
            for stage, adapter in adapters.items()
        )
    ):
        raise CausalRuntimeBridgeError(
            "causal runtime adapters must be either the exact optional/kernel "
            "subset or the exact full live route"
        )
    proof_context_value = _mapping(proof_context, "proof_context")
    # Construction performs the exact proof-context shape and source-only input
    # checks before any live adapter is invoked.
    base_request = StageRequest(
        run_id=semantic_result.run_id,
        case_id=semantic_result.case_id,
        case_manifest_sha256=semantic_result.case_manifest_sha256,
        variant_id=semantic_result.variant_id,
        split=semantic_result.split,
        cache_mode=semantic_result.cache_mode,
        input_data={"text": source_text},
        requested_identity={},
        environment_sha256=frontend[0].provenance.environment_sha256,
        source=("causal_runtime_v2", compiler_exposure.receipt_cid),
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        proof_context=proof_context_value,
    )
    proof_context_cid = base_request.proof_context_cid
    if proof_context_cid is None:
        raise CausalRuntimeBridgeError(
            "causal runtime requires a reviewed proof context"
        )
    try:
        compiled_obligation = compile_reviewed_obligation(
            base_request.proof_input_data  # type: ignore[arg-type]
        )
    except (ProtocolContractError, RuntimeBindingError) as exc:
        raise CausalRuntimeBridgeError(
            "causal runtime proof context failed preflight compilation"
        ) from exc
    if compiled_obligation is None:
        raise CausalRuntimeBridgeError(
            "causal runtime proof context contains no reviewed obligation"
        )

    proof_compiler_artifact, compiler_candidate = (
        _proof_compiler_binding(
            compiler_exposure,
            source_text=source_text,
            proof_context=proof_context_value,
        )
    )
    runtime_artifacts: list[StageArtifact] = [
        proof_compiler_artifact
    ]
    for record in frontend:
        if record.stage is StageName.COMPILER:
            continue
        runtime_artifacts.append(
            _stage_artifact(
                record,
                invocation_index=len(runtime_artifacts),
                policy_reason="immutable_g200_semantic_frontend",
            )
        )
    optional_invocations: dict[StageName, StageInvocation] = {}
    optional_artifacts: dict[StageName, StageArtifact] = {}
    candidate_artifacts: dict[str, StageArtifact] = {}
    if compiler_candidate is not None:
        assert compiler_candidate.candidate_cid is not None
        candidate_artifacts[
            compiler_candidate.candidate_cid
        ] = compiler_exposure.artifact
    kernel_invocations: list[StageInvocation] = []
    kernel_requests: list[StageRequest] = []
    kernel_checks: dict[str, CausalKernelCheck] = {}
    exposure_cid = compiler_exposure.receipt_cid

    def request_for(
        stage: StageName,
        *,
        invocation_index: int,
        artifacts: tuple[StageArtifact, ...] | None = None,
    ) -> StageRequest:
        return replace(
            base_request,
            requested_identity=_runtime_identity(
                semantic_result.variant_id, stage, exposure_cid
            ),
            upstream_artifacts=(
                tuple(runtime_artifacts)
                if artifacts is None
                else artifacts
            ),
            invocation_index=invocation_index,
        )

    optional_producers: dict[
        str,
        Callable[[], CausalProofCandidate | CausalProofFailure],
    ] = {}
    for stage in profile.optional_order:
        adapter = adapters[stage]

        def produce(
            stage: StageName = stage,
            adapter: StageAdapter = adapter,
        ) -> CausalProofCandidate | CausalProofFailure:
            invocation_index = len(runtime_artifacts)
            request = request_for(
                stage, invocation_index=invocation_index
            )
            invocation = adapter.invoke(request)
            effective = {
                **dict(invocation.output.effective_identity),
                "graph_invoked": True,
                "graph_invocation_index": invocation_index,
                "policy_reason": "g210_optional_trigger",
                "causal_proof_protocol_cid": (
                    CAUSAL_PROOF_PROTOCOL_V2_CID
                ),
                "causal_variant_profile_cid": (
                    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
                ),
                "compiler_reference_exposure_cid": exposure_cid,
                "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
                "source_cid": source_cid,
                "proof_context_cid": proof_context_cid,
            }
            invocation = StageInvocation(
                replace(
                    invocation.output,
                    effective_identity=effective,
                ),
                invocation.telemetry,
            )
            artifact = _artifact_from_invocation(
                stage,
                invocation,
                invocation_index=invocation_index,
                policy_reason="g210_optional_trigger",
            )
            optional_invocations[stage] = invocation
            optional_artifacts[stage] = artifact
            runtime_artifacts.append(artifact)
            certificate = _certificate_from_output(
                stage, invocation.output
            )
            if certificate is None:
                return _proof_failure(stage, invocation.output)
            artifact_cid = _artifact_cid(artifact)
            candidate = CausalProofCandidate(
                source=stage.value,
                certificate=certificate,
                artifact_cid=artifact_cid,
            )
            assert candidate.candidate_cid is not None
            candidate_artifacts[candidate.candidate_cid] = artifact
            return candidate

        optional_producers[stage.value] = produce

    kernel_adapter = adapters[StageName.KERNEL]

    def invoke_kernel(
        candidate: CausalProofCandidate | None,
    ) -> tuple[StageInvocation, StageRequest, CausalKernelCheck | None]:
        invocation_index = min(len(StageName) - 1, len(runtime_artifacts))
        artifacts = tuple(runtime_artifacts)
        request = request_for(
            StageName.KERNEL,
            invocation_index=invocation_index,
            artifacts=artifacts,
        )
        if candidate is not None:
            candidate_artifact = candidate_artifacts.get(
                str(candidate.candidate_cid)
            )
            if candidate_artifact is None:
                raise CausalRuntimeBridgeError(
                    "native target lacks its exact producer artifact"
                )
            request = replace(
                request,
                requested_identity={
                    **dict(request.requested_identity),
                    "causal_target_candidate_source": candidate.source,
                    "causal_target_candidate_cid": (
                        candidate.candidate_cid
                    ),
                    "causal_target_candidate_artifact_cid": (
                        candidate.artifact_cid
                    ),
                    "causal_target_candidate_artifact_sha256": (
                        _artifact_sha256(candidate_artifact)
                    ),
                },
            )
        invocation = kernel_adapter.invoke(request)
        candidate_cid = (
            None if candidate is None else candidate.candidate_cid
        )
        effective = {
            **dict(invocation.output.effective_identity),
            "graph_invoked": True,
            "graph_invocation_index": invocation_index,
            "policy_reason": "g210_independent_native_kernel",
            "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
            "causal_variant_profile_cid": (
                CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
            ),
            "compiler_reference_exposure_cid": exposure_cid,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": source_cid,
            "proof_context_cid": proof_context_cid,
            "candidate_cid": candidate_cid,
            "consumed_artifact_sha256": tuple(
                artifact.digest for artifact in artifacts
            ),
        }
        invocation = StageInvocation(
            replace(
                invocation.output,
                effective_identity=effective,
            ),
            invocation.telemetry,
        )
        output = invocation.output
        consumed = tuple(artifact.digest for artifact in artifacts)
        try:
            accepted = validate_native_kernel_receipt(
                output.data,
                protocol_sha256=DEFAULT_PROTOCOL_SHA256,
                run_id=request.run_id,
                case_id=request.case_id,
                case_manifest_sha256=request.case_manifest_sha256,
                variant_id=request.variant_id,
                split=request.split,
                cache_mode=request.cache_mode,
                input_sha256=request.input_sha256,
                environment_sha256=request.environment_sha256,
                stage_status=output.status,
                kernel_accepted=output.kernel_accepted,
                kernel_receipt_sha256=output.kernel_receipt_sha256,
                consumed_artifact_sha256s=consumed,
                failure_code=output.failure_code,
            )
        except ProtocolContractError as exc:
            raise CausalRuntimeBridgeError(
                "native kernel emitted an invalid source-bound receipt"
            ) from exc
        kernel_invocations.append(invocation)
        kernel_requests.append(request)
        if candidate is None:
            if accepted:
                raise CausalRuntimeBridgeError(
                    "native kernel accepted without a candidate"
                )
            return invocation, request, None
        assert candidate_cid is not None
        artifact = candidate_artifacts.get(candidate_cid)
        if artifact is None:
            raise CausalRuntimeBridgeError(
                "native kernel checked an unbound candidate"
            )
        artifact_sha256 = sha256_digest_for_cid(
            candidate.artifact_cid, codecs=("raw",)
        )
        receipt = _mapping(output.data, "native kernel receipt")
        attempts = receipt.get("candidate_attempts")
        try:
            compiled = compile_reviewed_obligation(
                base_request.proof_input_data  # type: ignore[arg-type]
            )
            if compiled is None:
                raise RuntimeBindingError(
                    "causal proof context compiled no obligation"
                )
            rendered_source_sha256 = hashlib.sha256(
                compiled.render(
                    candidate.certificate.decode("utf-8")
                ).encode("utf-8")
            ).hexdigest()
        except (AttributeError, RuntimeBindingError) as exc:
            raise CausalRuntimeBridgeError(
                "native target source could not be independently rebuilt"
            ) from exc
        if (
            candidate.artifact_cid
            != _artifact_cid(artifact)
            or artifact.digest != artifact_sha256
            or receipt.get("candidate_source") != candidate.source
            or receipt.get("candidate_artifact_sha256")
            != artifact_sha256
            or receipt.get("compiled_obligation_sha256")
            != compiled.digest
            or receipt.get("obligation_sha256")
            != compiled.obligation_sha256
            or receipt.get("source_sha256")
            != rendered_source_sha256
            or not isinstance(attempts, (list, tuple))
            or len(attempts) != 1
            or artifact_sha256 not in consumed
        ):
            raise CausalRuntimeBridgeError(
                "native receipt candidate SHA-256 differs from the candidate "
                "artifact CID multihash"
            )
        check = CausalKernelCheck(
            candidate_cid=candidate_cid,
            accepted=accepted,
            receipt=receipt,
            stage_status=output.status,
            failure_code=output.failure_code,
            consumed_artifact_sha256s=consumed,
        )
        kernel_checks[candidate_cid] = check
        return invocation, request, check

    def checker(candidate: CausalProofCandidate) -> CausalKernelCheck:
        _invocation, _request, check = invoke_kernel(candidate)
        if check is None:  # pragma: no cover - candidate is non-null
            raise CausalRuntimeBridgeError(
                "candidate check produced no receipt"
            )
        return check

    def replay_check(
        candidate: CausalProofCandidate,
        check: CausalKernelCheck,
    ) -> bool:
        recorded = kernel_checks.get(str(candidate.candidate_cid))
        if recorded != check:
            return False
        artifact = candidate_artifacts.get(str(candidate.candidate_cid))
        if artifact is None:
            return False
        receipt_value = _plain(check.receipt)
        if not isinstance(receipt_value, Mapping):
            return False
        try:
            accepted = validate_native_kernel_receipt(
                receipt_value,
                protocol_sha256=semantic_result.protocol_sha256,
                run_id=semantic_result.run_id,
                case_id=semantic_result.case_id,
                case_manifest_sha256=(
                    semantic_result.case_manifest_sha256
                ),
                variant_id=semantic_result.variant_id,
                split=semantic_result.split,
                cache_mode=semantic_result.cache_mode,
                input_sha256=base_request.input_sha256,
                environment_sha256=base_request.environment_sha256,
                stage_status=check.stage_status,
                kernel_accepted=check.accepted,
                kernel_receipt_sha256=(
                    str(receipt_value["receipt_sha256"])
                    if check.accepted
                    else None
                ),
                consumed_artifact_sha256s=(
                    check.consumed_artifact_sha256s
                ),
                failure_code=check.failure_code,
            )
        except (KeyError, ProtocolContractError):
            return False
        artifact_sha256 = sha256_digest_for_cid(
            candidate.artifact_cid, codecs=("raw",)
        )
        attempts = receipt_value.get("candidate_attempts")
        return bool(
            accepted is check.accepted
            and candidate.artifact_cid
            == _artifact_cid(artifact)
            and receipt_value.get("candidate_artifact_sha256")
            == artifact_sha256
            and isinstance(attempts, (list, tuple))
            and len(attempts) == 1
            and artifact_sha256 in check.consumed_artifact_sha256s
        )

    controller = CausalProofGraphController(
        kernel_checker=checker,
        kernel_receipt_validator=replay_check,
    )
    try:
        selection_result = controller.execute(
            run_id=semantic_result.run_id,
            case_id=semantic_result.case_id,
            variant_id=semantic_result.variant_id,
            source_text=source_text,
            compiler_candidate=compiler_candidate,
            optional_producers=optional_producers,
        )
    except RuntimeBindingError as exc:
        raise CausalRuntimeBridgeError(
            "causal proof controller failed closed"
        ) from exc
    if not kernel_invocations:
        invoke_kernel(None)

    records: list[StageRecord] = list(frontend)
    canonical_upstream = tuple(record.digest for record in records)
    for stage in tuple(StageName):
        invocation = optional_invocations.get(stage)
        if invocation is None:
            continue
        artifact = optional_artifacts[stage]
        request = replace(
            request_for(
                stage,
                invocation_index=artifact.invocation_index,
            ),
            upstream_stage_digests=canonical_upstream,
        )
        record = adapters[stage].record(request, invocation)
        records.append(record)
        canonical_upstream = (*canonical_upstream, record.digest)

    terminal_invocation = kernel_invocations[-1]
    terminal_request = replace(
        kernel_requests[-1],
        upstream_stage_digests=canonical_upstream,
        upstream_artifacts=tuple(runtime_artifacts),
    )
    terminal_identity = {
        **dict(terminal_invocation.output.effective_identity),
        "causal_selection_receipt_cid": (
            selection_result.receipt_cid
        ),
        "compiler_reference_exposure_cid": exposure_cid,
        "kernel_check_count": len(kernel_invocations),
    }
    terminal_invocation = StageInvocation(
        replace(
            terminal_invocation.output,
            effective_identity=terminal_identity,
            telemetry=_aggregate_kernel_telemetry(
                kernel_invocations
            ),
        ),
        _aggregate_kernel_telemetry(kernel_invocations),
    )
    kernel_record = kernel_adapter.record(
        terminal_request, terminal_invocation
    )
    records.append(kernel_record)
    try:
        case_result = CaseResultRecord.from_stages(tuple(records))
        causal_receipt = build_causal_rescue_case_receipt(
            case_result, selection_result.receipt
        )
    except (ProtocolContractError, ValueError) as exc:
        raise CausalRuntimeBridgeError(
            "terminal G210 CaseResult failed receipt validation"
        ) from exc
    telemetry_receipts = tuple(
        MappingProxyType(
            {
                "candidate_cid": (
                    invocation.output.effective_identity.get(
                        "candidate_cid"
                    )
                ),
                "native_receipt_cid": cid_for_dag_json(
                    _plain(invocation.output.data)
                ),
                "telemetry": invocation.telemetry.to_dict(),
            }
        )
        for invocation in kernel_invocations
    )
    evidence = CausalRuntimeEvidenceV2(
        compiler_exposure=compiler_exposure,
        semantic_frontend=frontend,
        selection_result=selection_result,
        case_result=case_result,
        causal_case_receipt=MappingProxyType(dict(causal_receipt)),
        kernel_check_telemetry=telemetry_receipts,
        source_text=source_text,
        proof_context=MappingProxyType(
            dict(_plain(proof_context_value))  # type: ignore[arg-type]
        ),
        proof_context_cid=proof_context_cid,
    )
    return validate_causal_runtime_evidence_v2(evidence.to_dict())


__all__ = [
    "CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2",
    "COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2",
    "CausalRuntimeBridgeError",
    "CausalRuntimeEvidenceV2",
    "CompilerReferenceExposureV2",
    "execute_causal_runtime_case_v2",
    "validate_causal_runtime_evidence_v2",
]
