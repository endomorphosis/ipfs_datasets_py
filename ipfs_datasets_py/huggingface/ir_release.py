"""Append-only proof-grounded IR release packaging.

PGIR-090 extends the existing Hugging Face read/release helpers with a
publication owner that:

* declares **separate P1 configs** (never a heterogeneous auto-detected schema);
* emits complete dataset and checkpoint cards;
* seals **P4 evidence** (compiler, decompiler, loss, proof, evaluation,
  promotion, rollback) as immutable content-addressed roots; and
* keeps source and derived counts distinct.

Local packaging never contacts a write endpoint.  Remote publication is a
separate, lease-and-approval gated step in :mod:`.ir_publisher`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Final

from ..logic.ir_core.identity import cid_v1_from_digest
from .publisher import _reject_secrets
from .release import (
    FileDescriptor,
    HuggingFaceReleaseError,
    canonical_json_bytes,
    describe_file,
    reject_identity_contamination,
    write_canonical_json,
)


IR_RELEASE_PACKAGE_SCHEMA: Final = "IRReleasePackage@1"
IR_RELEASE_ROOT_SCHEMA: Final = "ir-append-only-release-root/v1"
IR_PUBLICATION_POLICY_SCHEMA: Final = "IRPublicationPolicy@1"
IR_P4_EVIDENCE_SCHEMA: Final = "IRPublicationEvidence@1"
IR_CONFIG_MANIFEST_SCHEMA: Final = "IRReleaseConfigManifest@1"
DEFAULT_IR_DATASET_REPO_ID: Final = "Publicus/proof-grounded-ir-learning"
DEFAULT_RELEASE_PREFIX_TEMPLATE: Final = "data/ir_learning/{release_id}"
DEFAULT_POINTER_PATH: Final = "runtime/ir_learning_release_pointer.json"
IR_RELEASE_PRODUCER: Final = "producer:pgir-090-ir-release"

# P1: each semantic population is an explicit, schema-homogeneous Hugging Face
# Dataset Viewer config.  Mixing them into one auto-detected config is refused.
P1_CONFIGS: Final[tuple[str, ...]] = (
    "source",
    "derived",
    "pairs_positive",
    "pairs_negative",
    "splits",
    "evaluations",
    "checkpoints",
    "proofs",
)

# P4: publication binds these identities as an immutable evidence root.
P4_EVIDENCE_KEYS: Final[tuple[str, ...]] = (
    "compiler_identity",
    "decompiler_identity",
    "loss_configuration_identity",
    "proof_root",
    "evaluation_root",
    "promotion_decision",
    "rollback_record",
)

_ADMITTED_PROMOTION_DECISIONS: Final = frozenset({"promote"})
_ADMITTED_CHECKPOINT_STATES: Final = frozenset({"promoted"})
_DIGEST_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class IRReleaseError(HuggingFaceReleaseError):
    """Raised when an IR release package cannot be built or validated."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise IRReleaseError(f"{label} must be a non-empty string without surrounding whitespace")
    if "\x00" in value:
        raise IRReleaseError(f"{label} must not contain NUL")
    return value


def _digest_hex(value: Any, *, label: str) -> str:
    text = _text(value, label=label).casefold()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    if not _DIGEST_HEX_RE.fullmatch(text):
        raise IRReleaseError(f"{label} must be a full lower-case 64-character hex digest")
    return text


def _non_negative_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise IRReleaseError(f"{label} must be a non-negative integer")
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IRReleaseError(f"{label} must be an object")
    return value


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise IRReleaseError(f"{label} must be an array")
    return value


def _load_json_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IRReleaseError(f"{label} is missing: {target}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IRReleaseError(f"{label} is not valid UTF-8 JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise IRReleaseError(f"{label} must be a JSON object")
    return payload


def _safe_release_id(value: Any) -> str:
    release = str(value or "").strip()
    if (
        not release
        or "/" in release
        or "\\" in release
        or ".." in release
        or release.startswith(".")
    ):
        raise IRReleaseError(f"unsafe release_id: {value!r}")
    return release


def _cid_for_bytes(payload: bytes) -> str:
    return cid_v1_from_digest(sha256(payload).digest())


def default_releases_data_dir() -> Path:
    """Return ``data/ir_learning/releases`` relative to the datasets package."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "ir_learning" / "releases"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "ipfs_datasets_py" / "data" / "ir_learning" / "releases"


@dataclass(frozen=True, slots=True)
class IRPublicationPolicy:
    """Fail-closed publication policy.  Default admission is deny."""

    schema: str = IR_PUBLICATION_POLICY_SCHEMA
    repository_id: str = DEFAULT_IR_DATASET_REPO_ID
    repository_type: str = "dataset"
    release_prefix_template: str = DEFAULT_RELEASE_PREFIX_TEMPLATE
    pointer_path: str = DEFAULT_POINTER_PATH
    append_only: bool = True
    require_qualification: bool = True
    require_human_approval: bool = True
    require_publication_lease: bool = True
    trust_remote_code: bool = False
    allow_auto_detected_schema: bool = False
    require_source_derived_separation: bool = True
    require_explicit_p1_configs: bool = True
    require_complete_cards: bool = True
    require_p4_evidence: bool = True
    default_publication_admission: str = "deny"
    lease_fence_template: str = "hf-publication:{repository_id}"
    license_id: str = "other"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema != IR_PUBLICATION_POLICY_SCHEMA:
            raise IRReleaseError("unsupported publication policy schema")
        repo = _text(self.repository_id, label="repository_id")
        if "/" not in repo or repo.startswith("/") or repo.endswith("/"):
            raise IRReleaseError("repository_id must have the form namespace/repository")
        repo_type = _text(self.repository_type, label="repository_type").casefold()
        if repo_type not in {"dataset", "model"}:
            raise IRReleaseError("repository_type must be dataset or model")
        template = _text(self.release_prefix_template, label="release_prefix_template")
        if "{release_id}" not in template:
            raise IRReleaseError("release_prefix_template must include {release_id}")
        if self.trust_remote_code:
            raise IRReleaseError("trust_remote_code is prohibited")
        if self.allow_auto_detected_schema:
            raise IRReleaseError("heterogeneous auto-detected schema is prohibited")
        if not self.append_only:
            raise IRReleaseError("publication must be append-only")
        if not self.require_qualification or not self.require_human_approval:
            raise IRReleaseError("unrestricted publication is prohibited")
        if not self.require_publication_lease:
            raise IRReleaseError("publication lease is required")
        if not self.require_source_derived_separation:
            raise IRReleaseError("source/derived counts must remain distinct")
        if not self.require_explicit_p1_configs:
            raise IRReleaseError("separate P1 configs are required")
        if not self.require_complete_cards:
            raise IRReleaseError("complete dataset/checkpoint cards are required")
        if not self.require_p4_evidence:
            raise IRReleaseError("P4 evidence is required")
        if self.default_publication_admission != "deny":
            raise IRReleaseError("default publication admission must deny")
        fence = _text(self.lease_fence_template, label="lease_fence_template")
        if "{repository_id}" not in fence:
            raise IRReleaseError("lease_fence_template must include {repository_id}")
        metadata = dict(self.metadata)
        _reject_secrets(metadata, label="publication_policy.metadata")
        object.__setattr__(self, "repository_id", repo)
        object.__setattr__(self, "repository_type", repo_type)
        object.__setattr__(self, "release_prefix_template", template)
        object.__setattr__(self, "pointer_path", _text(self.pointer_path, label="pointer_path"))
        object.__setattr__(self, "lease_fence_template", fence)
        object.__setattr__(self, "license_id", _text(self.license_id, label="license_id"))
        object.__setattr__(self, "metadata", metadata)

    @property
    def lease_fence(self) -> str:
        return self.lease_fence_template.format(repository_id=self.repository_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_auto_detected_schema": False,
            "append_only": True,
            "default_publication_admission": "deny",
            "lease_fence": self.lease_fence,
            "lease_fence_template": self.lease_fence_template,
            "license_id": self.license_id,
            "metadata": dict(self.metadata),
            "pointer_path": self.pointer_path,
            "release_prefix_template": self.release_prefix_template,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "require_complete_cards": True,
            "require_explicit_p1_configs": True,
            "require_human_approval": True,
            "require_p4_evidence": True,
            "require_publication_lease": True,
            "require_qualification": True,
            "require_source_derived_separation": True,
            "schema": self.schema,
            "trust_remote_code": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IRPublicationPolicy":
        payload = _require_mapping(value, "publication policy")
        return cls(
            schema=str(payload.get("schema") or IR_PUBLICATION_POLICY_SCHEMA),
            repository_id=str(payload.get("repository_id") or DEFAULT_IR_DATASET_REPO_ID),
            repository_type=str(payload.get("repository_type") or "dataset"),
            release_prefix_template=str(
                payload.get("release_prefix_template") or DEFAULT_RELEASE_PREFIX_TEMPLATE
            ),
            pointer_path=str(payload.get("pointer_path") or DEFAULT_POINTER_PATH),
            append_only=bool(payload.get("append_only", True)),
            require_qualification=bool(payload.get("require_qualification", True)),
            require_human_approval=bool(payload.get("require_human_approval", True)),
            require_publication_lease=bool(payload.get("require_publication_lease", True)),
            trust_remote_code=bool(payload.get("trust_remote_code", False)),
            allow_auto_detected_schema=bool(payload.get("allow_auto_detected_schema", False)),
            require_source_derived_separation=bool(
                payload.get("require_source_derived_separation", True)
            ),
            require_explicit_p1_configs=bool(payload.get("require_explicit_p1_configs", True)),
            require_complete_cards=bool(payload.get("require_complete_cards", True)),
            require_p4_evidence=bool(payload.get("require_p4_evidence", True)),
            default_publication_admission=str(
                payload.get("default_publication_admission") or "deny"
            ),
            lease_fence_template=str(
                payload.get("lease_fence_template") or "hf-publication:{repository_id}"
            ),
            license_id=str(payload.get("license_id") or "other"),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        )


def load_publication_policy(path: str | Path | None = None) -> IRPublicationPolicy:
    """Load the sealed campaign publication policy."""

    target = Path(path) if path is not None else default_releases_data_dir() / "publication_policy.json"
    return IRPublicationPolicy.from_dict(_load_json_mapping(target, label="publication policy"))


@dataclass(frozen=True, slots=True)
class QualifiedReleaseInputs:
    """Qualified release/checkpoint/evaluation/proof identities for one package."""

    corpus_root: str
    split_root: str
    checkpoint_id: str
    checkpoint_digest: str
    checkpoint_lifecycle_state: str
    checkpoint_authority: bool
    compiler_identity: str
    decompiler_identity: str
    loss_configuration_identity: str
    evaluation_root: str
    proof_root: str
    promotion_decision: str
    promotion_receipt: str
    source_count: int
    derived_count: int
    pairs_positive_count: int = 0
    pairs_negative_count: int = 0
    evaluation_count: int = 0
    proof_count: int = 0
    rollback_record: str = ""
    training_admitted_rows: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_root", _text(self.corpus_root, label="corpus_root"))
        object.__setattr__(self, "split_root", _text(self.split_root, label="split_root"))
        object.__setattr__(self, "checkpoint_id", _text(self.checkpoint_id, label="checkpoint_id"))
        object.__setattr__(
            self,
            "checkpoint_digest",
            _digest_hex(self.checkpoint_digest, label="checkpoint_digest"),
        )
        state = _text(self.checkpoint_lifecycle_state, label="checkpoint_lifecycle_state")
        if state not in _ADMITTED_CHECKPOINT_STATES:
            raise IRReleaseError(
                "only an admitted promoted RESULT(PGIR-070) checkpoint may be packaged"
            )
        if not self.checkpoint_authority:
            raise IRReleaseError("checkpoint authority is required for qualified publication")
        decision = _text(self.promotion_decision, label="promotion_decision")
        if decision not in _ADMITTED_PROMOTION_DECISIONS:
            raise IRReleaseError(
                f"publication requires a promote decision, got {decision!r}"
            )
        if self.source_count == self.derived_count and self.source_count > 0:
            # Not inherently illegal, but official corpora keep them distinct.
            # The hard rule is that they must be reported separately, which
            # validation enforces via distinct fields.
            pass
        object.__setattr__(self, "checkpoint_lifecycle_state", state)
        object.__setattr__(self, "promotion_decision", decision)
        object.__setattr__(
            self, "compiler_identity", _text(self.compiler_identity, label="compiler_identity")
        )
        object.__setattr__(
            self, "decompiler_identity", _text(self.decompiler_identity, label="decompiler_identity")
        )
        object.__setattr__(
            self,
            "loss_configuration_identity",
            _text(self.loss_configuration_identity, label="loss_configuration_identity"),
        )
        object.__setattr__(
            self, "evaluation_root", _text(self.evaluation_root, label="evaluation_root")
        )
        object.__setattr__(self, "proof_root", _text(self.proof_root, label="proof_root"))
        object.__setattr__(
            self, "promotion_receipt", _text(self.promotion_receipt, label="promotion_receipt")
        )
        object.__setattr__(self, "source_count", _non_negative_int(self.source_count, label="source_count"))
        object.__setattr__(
            self, "derived_count", _non_negative_int(self.derived_count, label="derived_count")
        )
        object.__setattr__(
            self,
            "pairs_positive_count",
            _non_negative_int(self.pairs_positive_count, label="pairs_positive_count"),
        )
        object.__setattr__(
            self,
            "pairs_negative_count",
            _non_negative_int(self.pairs_negative_count, label="pairs_negative_count"),
        )
        object.__setattr__(
            self,
            "evaluation_count",
            _non_negative_int(self.evaluation_count, label="evaluation_count"),
        )
        object.__setattr__(
            self, "proof_count", _non_negative_int(self.proof_count, label="proof_count")
        )
        object.__setattr__(
            self,
            "training_admitted_rows",
            _non_negative_int(self.training_admitted_rows, label="training_admitted_rows"),
        )
        rollback = str(self.rollback_record or "none/no-prior-release")
        object.__setattr__(self, "rollback_record", rollback)
        metadata = dict(self.metadata)
        _reject_secrets(metadata, label="qualified_inputs.metadata")
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_authority": True,
            "checkpoint_digest": self.checkpoint_digest,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_lifecycle_state": self.checkpoint_lifecycle_state,
            "compiler_identity": self.compiler_identity,
            "corpus_root": self.corpus_root,
            "decompiler_identity": self.decompiler_identity,
            "derived_count": self.derived_count,
            "evaluation_count": self.evaluation_count,
            "evaluation_root": self.evaluation_root,
            "loss_configuration_identity": self.loss_configuration_identity,
            "metadata": dict(self.metadata),
            "pairs_negative_count": self.pairs_negative_count,
            "pairs_positive_count": self.pairs_positive_count,
            "promotion_decision": self.promotion_decision,
            "promotion_receipt": self.promotion_receipt,
            "proof_count": self.proof_count,
            "proof_root": self.proof_root,
            "rollback_record": self.rollback_record,
            "source_count": self.source_count,
            "split_root": self.split_root,
            "training_admitted_rows": self.training_admitted_rows,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualifiedReleaseInputs":
        payload = _require_mapping(value, "qualified release inputs")
        checkpoint = payload.get("checkpoint")
        if isinstance(checkpoint, Mapping):
            checkpoint_id = checkpoint.get("checkpoint_id") or payload.get("checkpoint_id")
            checkpoint_digest = (
                checkpoint.get("digest")
                or checkpoint.get("checkpoint_digest")
                or payload.get("checkpoint_digest")
            )
            lifecycle = checkpoint.get("lifecycle_state") or payload.get(
                "checkpoint_lifecycle_state"
            )
            authority = checkpoint.get("authority", payload.get("checkpoint_authority"))
        else:
            checkpoint_id = payload.get("checkpoint_id")
            checkpoint_digest = payload.get("checkpoint_digest")
            lifecycle = payload.get("checkpoint_lifecycle_state")
            authority = payload.get("checkpoint_authority")
        promotion = payload.get("promotion")
        if isinstance(promotion, Mapping):
            decision = promotion.get("decision") or payload.get("promotion_decision")
            receipt = promotion.get("receipt") or payload.get("promotion_receipt")
        else:
            decision = payload.get("promotion_decision")
            receipt = payload.get("promotion_receipt")
        counts = payload.get("counts") if isinstance(payload.get("counts"), Mapping) else payload
        identities = (
            payload.get("identities")
            if isinstance(payload.get("identities"), Mapping)
            else payload
        )
        return cls(
            corpus_root=str(payload.get("corpus_root") or ""),
            split_root=str(payload.get("split_root") or ""),
            checkpoint_id=str(checkpoint_id or ""),
            checkpoint_digest=str(checkpoint_digest or ""),
            checkpoint_lifecycle_state=str(lifecycle or ""),
            checkpoint_authority=bool(authority),
            compiler_identity=str(identities.get("compiler_identity") or ""),
            decompiler_identity=str(identities.get("decompiler_identity") or ""),
            loss_configuration_identity=str(
                identities.get("loss_configuration_identity") or ""
            ),
            evaluation_root=str(
                payload.get("evaluation_root") or identities.get("evaluation_root") or ""
            ),
            proof_root=str(payload.get("proof_root") or identities.get("proof_root") or ""),
            promotion_decision=str(decision or ""),
            promotion_receipt=str(receipt or ""),
            source_count=int(counts.get("source_count", -1)),
            derived_count=int(counts.get("derived_count", -1)),
            pairs_positive_count=int(counts.get("pairs_positive_count", 0)),
            pairs_negative_count=int(counts.get("pairs_negative_count", 0)),
            evaluation_count=int(counts.get("evaluation_count", 0)),
            proof_count=int(counts.get("proof_count", 0)),
            rollback_record=str(payload.get("rollback_record") or ""),
            training_admitted_rows=int(counts.get("training_admitted_rows", 0)),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        )


def load_qualified_inputs(path: str | Path | None = None) -> QualifiedReleaseInputs:
    target = Path(path) if path is not None else default_releases_data_dir() / "qualified_inputs.json"
    return QualifiedReleaseInputs.from_dict(_load_json_mapping(target, label="qualified inputs"))


def build_p4_evidence(inputs: QualifiedReleaseInputs) -> dict[str, Any]:
    """Seal compiler/loss/proof/evaluation/promotion/rollback identities."""

    evidence = {
        "compiler_identity": inputs.compiler_identity,
        "decompiler_identity": inputs.decompiler_identity,
        "evaluation_root": inputs.evaluation_root,
        "loss_configuration_identity": inputs.loss_configuration_identity,
        "promotion_decision": {
            "decision": inputs.promotion_decision,
            "receipt": inputs.promotion_receipt,
        },
        "proof_root": inputs.proof_root,
        "rollback_record": inputs.rollback_record,
        "schema": IR_P4_EVIDENCE_SCHEMA,
    }
    missing = [key for key in P4_EVIDENCE_KEYS if key not in evidence or evidence[key] in ("", None)]
    if missing:
        raise IRReleaseError("P4 evidence is incomplete: " + ", ".join(missing))
    _reject_secrets(evidence, label="p4_evidence")
    reject_identity_contamination(evidence, label="p4_evidence")
    body = canonical_json_bytes(evidence)
    evidence["evidence_sha256"] = sha256(body).hexdigest()
    evidence["evidence_cid"] = _cid_for_bytes(body)
    return evidence


def _config_rows(config_name: str, inputs: QualifiedReleaseInputs) -> list[dict[str, Any]]:
    """Compact, schema-homogeneous rows for one P1 config."""

    if config_name == "source":
        return [
            {
                "kind": "source_count_row",
                "record_id": "src:release-summary:0000",
                "corpus_root": inputs.corpus_root,
                "row_count": inputs.source_count,
                "training_admitted_rows": inputs.training_admitted_rows,
            }
        ]
    if config_name == "derived":
        return [
            {
                "kind": "derived_count_row",
                "record_id": "drv:release-summary:0000",
                "corpus_root": inputs.corpus_root,
                "row_count": inputs.derived_count,
                "parent_kind": "source",
            }
        ]
    if config_name == "pairs_positive":
        return [
            {
                "kind": "pairs_positive_summary",
                "record_id": "pair:positive:release-summary",
                "row_count": inputs.pairs_positive_count,
                "split_root": inputs.split_root,
            }
        ]
    if config_name == "pairs_negative":
        return [
            {
                "kind": "pairs_negative_summary",
                "record_id": "pair:negative:release-summary",
                "row_count": inputs.pairs_negative_count,
                "split_root": inputs.split_root,
            }
        ]
    if config_name == "splits":
        return [
            {
                "kind": "split_root_row",
                "record_id": "split:release-summary",
                "split_root": inputs.split_root,
                "source_count": inputs.source_count,
                "derived_count": inputs.derived_count,
            }
        ]
    if config_name == "evaluations":
        return [
            {
                "kind": "evaluation_root_row",
                "record_id": "eval:release-summary",
                "evaluation_root": inputs.evaluation_root,
                "row_count": inputs.evaluation_count,
            }
        ]
    if config_name == "checkpoints":
        return [
            {
                "kind": "checkpoint_ref",
                "record_id": inputs.checkpoint_id,
                "checkpoint_digest": inputs.checkpoint_digest,
                "lifecycle_state": inputs.checkpoint_lifecycle_state,
                "authority": True,
            }
        ]
    if config_name == "proofs":
        return [
            {
                "kind": "proof_root_row",
                "record_id": "proof:release-summary",
                "proof_root": inputs.proof_root,
                "row_count": inputs.proof_count,
            }
        ]
    raise IRReleaseError(f"unknown P1 config: {config_name}")


def render_dataset_card(
    *,
    release_id: str,
    policy: IRPublicationPolicy,
    inputs: QualifiedReleaseInputs,
    evidence: Mapping[str, Any],
    row_counts: Mapping[str, int],
) -> str:
    """Complete dataset card with explicit P1 configs (no auto-detect)."""

    lines = [
        "---",
        f"license: {policy.license_id}",
        f"dataset_repo_id: {policy.repository_id}",
        f"release_id: {release_id}",
        "pretty_name: Proof-Grounded IR Learning Release",
        "trust_remote_code: false",
        "configs:",
    ]
    for config_name in P1_CONFIGS:
        lines.append(f"- config_name: {config_name}")
        lines.append("  data_files:")
        lines.append("  - split: train")
        lines.append(f"    path: configs/{config_name}/train/{config_name}-*.json")
    lines.extend(
        [
            "---",
            "",
            f"# Proof-grounded IR release `{release_id}`",
            "",
            "Append-only qualified Hugging Face package.  Each P1 config is a",
            "separately declared, schema-homogeneous Viewer configuration.",
            "Heterogeneous auto-detected schemas are refused.",
            "",
            "Publication is versioned and append-only.  Remote upload requires a",
            f"`{policy.lease_fence}` lease, qualification, and human approval.",
            "",
            "## Source versus derived counts",
            "",
            f"- source rows: `{inputs.source_count}`",
            f"- derived rows: `{inputs.derived_count}`",
            f"- training admitted rows: `{inputs.training_admitted_rows}`",
            "",
            "Source and derived populations are distinct and never mixed in one",
            "config.  Derivatives do not inflate source counts.",
            "",
            "## P1 configs",
            "",
        ]
    )
    for config_name in P1_CONFIGS:
        lines.append(f"- `{config_name}`: {int(row_counts.get(config_name, 0))} rows")
    lines.extend(
        [
            "",
            "## Bound identities",
            "",
            f"- corpus root: `{inputs.corpus_root}`",
            f"- split root: `{inputs.split_root}`",
            f"- compiler: `{inputs.compiler_identity}`",
            f"- decompiler: `{inputs.decompiler_identity}`",
            f"- loss: `{inputs.loss_configuration_identity}`",
            f"- evaluation root: `{inputs.evaluation_root}`",
            f"- proof root: `{inputs.proof_root}`",
            f"- P4 evidence CID: `{evidence.get('evidence_cid', '')}`",
            "",
            "This card is generated offline.  Tokens and credentials never appear",
            "in cards, manifests, or receipts.",
            "",
        ]
    )
    return "\n".join(lines)


def render_checkpoint_card(
    *,
    release_id: str,
    inputs: QualifiedReleaseInputs,
    evidence: Mapping[str, Any],
) -> str:
    """Complete checkpoint card for the admitted RESULT(PGIR-070) identity."""

    return "\n".join(
        [
            f"# Checkpoint card for `{inputs.checkpoint_id}`",
            "",
            f"Release: `{release_id}`",
            f"Digest: `sha256:{inputs.checkpoint_digest}`",
            f"Lifecycle: `{inputs.checkpoint_lifecycle_state}`",
            "Authority: admitted (promoted); the checkpoint cannot self-promote.",
            "",
            "## Bound training identities",
            "",
            f"- compiler: `{inputs.compiler_identity}`",
            f"- decompiler: `{inputs.decompiler_identity}`",
            f"- loss configuration: `{inputs.loss_configuration_identity}`",
            f"- corpus root: `{inputs.corpus_root}`",
            f"- split root: `{inputs.split_root}`",
            "",
            "## P4 evidence",
            "",
            f"- evaluation root: `{inputs.evaluation_root}`",
            f"- proof root: `{inputs.proof_root}`",
            f"- promotion decision: `{inputs.promotion_decision}`",
            f"- promotion receipt: `{inputs.promotion_receipt}`",
            f"- rollback/supersession record: `{inputs.rollback_record}`",
            f"- evidence CID: `{evidence.get('evidence_cid', '')}`",
            "",
            "Loss improvement alone cannot authorize publication.  Only an",
            "admitted promotion decision plus this card may travel with the",
            "append-only package.",
            "",
        ]
    )


def _describe_under(root: Path, path: Path, **kwargs: Any) -> FileDescriptor:
    return describe_file(path, root=root, **kwargs)


@dataclass(frozen=True, slots=True)
class IRReleasePackage:
    """Local, content-addressed IR release package."""

    output_dir: str
    release_id: str
    release_sha256: str
    release_cid: str
    repository_id: str
    configs: tuple[str, ...]
    source_count: int
    derived_count: int
    row_counts: Mapping[str, int]
    evidence_cid: str
    manifest_path: str
    dataset_card_path: str
    checkpoint_card_path: str
    descriptors: tuple[FileDescriptor, ...]
    policy_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_card_path": self.checkpoint_card_path,
            "configs": list(self.configs),
            "dataset_card_path": self.dataset_card_path,
            "derived_count": self.derived_count,
            "descriptors": [item.to_dict() for item in self.descriptors],
            "evidence_cid": self.evidence_cid,
            "manifest_path": self.manifest_path,
            "output_dir": self.output_dir,
            "policy_digest": self.policy_digest,
            "release_cid": self.release_cid,
            "release_id": self.release_id,
            "release_sha256": self.release_sha256,
            "repository_id": self.repository_id,
            "row_counts": dict(self.row_counts),
            "schema": IR_RELEASE_PACKAGE_SCHEMA,
            "source_count": self.source_count,
        }

    def publication_manifest(self) -> dict[str, Any]:
        """Manifest consumed by the append-only publisher."""

        return {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "files": [
                {
                    "content_cid": item.content_cid,
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in self.descriptors
            ],
            "release_cid": self.release_cid,
            "release_id": self.release_id,
            "release_sha256": self.release_sha256,
            "repository_id": self.repository_id,
            "schema": IR_RELEASE_PACKAGE_SCHEMA,
            "source_count": self.source_count,
            "derived_count": self.derived_count,
        }


def package_ir_release(
    *,
    output_dir: str | Path,
    inputs: QualifiedReleaseInputs | Mapping[str, Any],
    policy: IRPublicationPolicy | Mapping[str, Any] | None = None,
    release_id: str | None = None,
) -> IRReleasePackage:
    """Build a deterministic local release package.

    Re-running with the same inputs yields a byte-identical package (idempotent).
    No network I/O is performed.
    """

    qualified = (
        inputs if isinstance(inputs, QualifiedReleaseInputs) else QualifiedReleaseInputs.from_dict(inputs)
    )
    pub_policy = (
        IRPublicationPolicy()
        if policy is None
        else policy
        if isinstance(policy, IRPublicationPolicy)
        else IRPublicationPolicy.from_dict(policy)
    )
    evidence = build_p4_evidence(qualified)
    policy_bytes = canonical_json_bytes(pub_policy.to_dict())
    policy_digest = sha256(policy_bytes).hexdigest()

    identity_payload = {
        "configs": list(P1_CONFIGS),
        "evidence_cid": evidence["evidence_cid"],
        "inputs": qualified.to_dict(),
        "policy_digest": policy_digest,
        "producer_id": IR_RELEASE_PRODUCER,
        "repository_id": pub_policy.repository_id,
        "schema": IR_RELEASE_PACKAGE_SCHEMA,
    }
    reject_identity_contamination(identity_payload, label="ir_release_identity")
    _reject_secrets(identity_payload, label="ir_release_identity")
    identity_digest = sha256(canonical_json_bytes(identity_payload)).hexdigest()
    resolved_release_id = _safe_release_id(release_id or f"sha256-{identity_digest}")

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    row_counts: dict[str, int] = {}
    descriptors: list[FileDescriptor] = []

    write_canonical_json(root / "publication_policy.json", pub_policy.to_dict())
    write_canonical_json(root / "evidence" / "p4_evidence.json", evidence)
    write_canonical_json(root / "counts" / "source_derived.json", {
        "derived_count": qualified.derived_count,
        "schema": "ir-release-source-derived-counts/v1",
        "source_count": qualified.source_count,
        "source_derived_distinct": qualified.source_count != qualified.derived_count
        or qualified.source_count == 0,
        "training_admitted_rows": qualified.training_admitted_rows,
    })

    for config_name in P1_CONFIGS:
        rows = _config_rows(config_name, qualified)
        row_counts[config_name] = len(rows)
        config_manifest = {
            "auto_detected": False,
            "config_name": config_name,
            "row_count": len(rows),
            "schema": IR_CONFIG_MANIFEST_SCHEMA,
            "schema_homogeneous": True,
            "split": "train",
        }
        write_canonical_json(root / "configs" / config_name / "config.json", config_manifest)
        shard_path = (
            root / "configs" / config_name / "train" / f"{config_name}-00000-of-00001.json"
        )
        write_canonical_json(shard_path, {"config_name": config_name, "rows": rows, "split": "train"})

    dataset_card = render_dataset_card(
        release_id=resolved_release_id,
        policy=pub_policy,
        inputs=qualified,
        evidence=evidence,
        row_counts=row_counts,
    )
    checkpoint_card = render_checkpoint_card(
        release_id=resolved_release_id,
        inputs=qualified,
        evidence=evidence,
    )
    (root / "README.md").write_text(dataset_card, encoding="utf-8")
    (root / "cards" / "dataset_card.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "cards" / "dataset_card.md").write_text(dataset_card, encoding="utf-8")
    (root / "cards" / "checkpoint_card.md").write_text(checkpoint_card, encoding="utf-8")
    (root / "CHECKPOINT_CARD.md").write_text(checkpoint_card, encoding="utf-8")

    missing_configs = [name for name in P1_CONFIGS if name not in row_counts]
    if missing_configs:
        raise IRReleaseError("P1 configs incomplete: " + ", ".join(missing_configs))
    if "auto-detect" in dataset_card.casefold() and "refused" not in dataset_card.casefold():
        raise IRReleaseError("dataset card must not rely on auto-detected schema")

    publishable = [
        "README.md",
        "CHECKPOINT_CARD.md",
        "publication_policy.json",
        "cards/dataset_card.md",
        "cards/checkpoint_card.md",
        "evidence/p4_evidence.json",
        "counts/source_derived.json",
    ]
    for config_name in P1_CONFIGS:
        publishable.append(f"configs/{config_name}/config.json")
        publishable.append(f"configs/{config_name}/train/{config_name}-00000-of-00001.json")

    for relative in publishable:
        path = root.joinpath(*relative.split("/"))
        if not path.is_file():
            raise IRReleaseError(f"package file missing: {relative}")
        descriptors.append(
            _describe_under(
                root,
                path,
                producer_id=IR_RELEASE_PRODUCER,
                config_name=relative.split("/", 2)[1] if relative.startswith("configs/") else "",
            )
        )
    descriptors.sort(key=lambda item: item.relative_path)

    package_identity = {
        **identity_payload,
        "release_id": resolved_release_id,
        "files": [
            {
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "content_cid": item.content_cid,
            }
            for item in descriptors
        ],
    }
    release_bytes = canonical_json_bytes(package_identity)
    release_sha256 = sha256(release_bytes).hexdigest()
    release_cid = _cid_for_bytes(release_bytes)

    manifest = {
        "configs": list(P1_CONFIGS),
        "derived_count": qualified.derived_count,
        "descriptors": [item.to_dict() for item in descriptors],
        "evidence_cid": evidence["evidence_cid"],
        "files": [
            {
                "content_cid": item.content_cid,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in descriptors
        ],
        "policy_digest": policy_digest,
        "release_cid": release_cid,
        "release_id": resolved_release_id,
        "release_sha256": release_sha256,
        "repository_id": pub_policy.repository_id,
        "row_counts": dict(row_counts),
        "schema": IR_RELEASE_PACKAGE_SCHEMA,
        "source_count": qualified.source_count,
    }
    write_canonical_json(root / "release_manifest.json", manifest)
    manifest_descriptor = _describe_under(root, root / "release_manifest.json")
    descriptors = tuple(sorted((*descriptors, manifest_descriptor), key=lambda item: item.relative_path))

    root_payload = {
        "derived_count": qualified.derived_count,
        "evidence_cid": evidence["evidence_cid"],
        "kind": IR_RELEASE_ROOT_SCHEMA,
        "policy_digest": policy_digest,
        "release_cid": release_cid,
        "release_id": resolved_release_id,
        "release_sha256": release_sha256,
        "repository_id": pub_policy.repository_id,
        "source_count": qualified.source_count,
    }
    write_canonical_json(root / "release_root.json", root_payload)

    return IRReleasePackage(
        output_dir=root.as_posix(),
        release_id=resolved_release_id,
        release_sha256=release_sha256,
        release_cid=release_cid,
        repository_id=pub_policy.repository_id,
        configs=P1_CONFIGS,
        source_count=qualified.source_count,
        derived_count=qualified.derived_count,
        row_counts=row_counts,
        evidence_cid=str(evidence["evidence_cid"]),
        manifest_path=(root / "release_manifest.json").as_posix(),
        dataset_card_path=(root / "README.md").as_posix(),
        checkpoint_card_path=(root / "CHECKPOINT_CARD.md").as_posix(),
        descriptors=descriptors,
        policy_digest=policy_digest,
    )


def validate_ir_release_package(root: str | Path) -> dict[str, Any]:
    """Fail-closed validation of a local IR release package."""

    package_root = Path(root).expanduser().resolve()
    manifest = _load_json_mapping(package_root / "release_manifest.json", label="release manifest")
    if manifest.get("schema") != IR_RELEASE_PACKAGE_SCHEMA:
        raise IRReleaseError("release manifest schema is not IRReleasePackage@1")
    configs = tuple(manifest.get("configs") or ())
    if configs != P1_CONFIGS:
        raise IRReleaseError("P1 configs are incomplete or reordered")
    source_count = _non_negative_int(manifest.get("source_count"), label="source_count")
    derived_count = _non_negative_int(manifest.get("derived_count"), label="derived_count")
    if "source_count" not in manifest or "derived_count" not in manifest:
        raise IRReleaseError("source and derived counts must be distinct fields")
    if source_count == derived_count and source_count > 0:
        # Distinct *fields* are required; equal values are allowed only when
        # both are zero.  Official corpora keep them unequal.
        counts = _load_json_mapping(
            package_root / "counts" / "source_derived.json", label="source/derived counts"
        )
        if not counts.get("source_derived_distinct"):
            raise IRReleaseError("source and derived counts must be reported as distinct")

    dataset_card = (package_root / "README.md").read_text(encoding="utf-8")
    checkpoint_card = (package_root / "CHECKPOINT_CARD.md").read_text(encoding="utf-8")
    for required in ("configs:", "source rows:", "derived rows:", "trust_remote_code: false"):
        if required not in dataset_card:
            raise IRReleaseError(f"dataset card missing {required!r}")
    for config_name in P1_CONFIGS:
        if f"config_name: {config_name}" not in dataset_card:
            raise IRReleaseError(f"dataset card missing P1 config {config_name}")
        config_dir = package_root / "configs" / config_name
        if not (config_dir / "config.json").is_file():
            raise IRReleaseError(f"missing config manifest for {config_name}")
        shards = list((config_dir / "train").glob(f"{config_name}-*.json"))
        if not shards:
            raise IRReleaseError(f"missing rows for P1 config {config_name}")
    for required in ("Lifecycle:", "compiler:", "P4 evidence", "Authority:"):
        if required not in checkpoint_card:
            raise IRReleaseError(f"checkpoint card missing {required!r}")

    evidence = _load_json_mapping(package_root / "evidence" / "p4_evidence.json", label="P4 evidence")
    for key in P4_EVIDENCE_KEYS:
        if key not in evidence:
            raise IRReleaseError(f"P4 evidence missing {key}")
    if evidence.get("schema") != IR_P4_EVIDENCE_SCHEMA:
        raise IRReleaseError("P4 evidence schema is not IRPublicationEvidence@1")

    files = _require_sequence(manifest.get("files") or manifest.get("descriptors"), "files")
    for entry in files:
        mapping = _require_mapping(entry, "file descriptor")
        descriptor = FileDescriptor.from_dict(mapping)
        described = describe_file(package_root.joinpath(*descriptor.relative_path.split("/")), root=package_root)
        if described.sha256 != descriptor.sha256 or described.size_bytes != descriptor.size_bytes:
            raise IRReleaseError(f"descriptor mismatch: {descriptor.relative_path}")

    policy = IRPublicationPolicy.from_dict(
        _load_json_mapping(package_root / "publication_policy.json", label="publication policy")
    )
    _reject_secrets(manifest, label="release_manifest")
    reject_identity_contamination(
        {key: value for key, value in manifest.items() if key not in {"descriptors", "files"}},
        label="release_manifest",
    )
    return {
        "configs": list(configs),
        "derived_count": derived_count,
        "evidence_cid": evidence.get("evidence_cid"),
        "ok": True,
        "policy_repository_id": policy.repository_id,
        "release_cid": manifest.get("release_cid"),
        "release_id": manifest.get("release_id"),
        "release_sha256": manifest.get("release_sha256"),
        "source_count": source_count,
    }


def package_from_official_recipe(
    output_dir: str | Path,
    *,
    releases_dir: str | Path | None = None,
) -> IRReleasePackage:
    """Rebuild the sealed fixture package from the compact official recipe."""

    base = Path(releases_dir) if releases_dir is not None else default_releases_data_dir()
    policy = load_publication_policy(base / "publication_policy.json")
    inputs = load_qualified_inputs(base / "qualified_inputs.json")
    recipe = _load_json_mapping(base / "recipe.json", label="release recipe")
    if recipe.get("schema") != "IRReleaseRecipe@1":
        raise IRReleaseError("official recipe schema is not IRReleaseRecipe@1")
    return package_ir_release(
        output_dir=output_dir,
        inputs=inputs,
        policy=policy,
        release_id=str(recipe.get("release_id") or "") or None,
    )


__all__ = [
    "DEFAULT_IR_DATASET_REPO_ID",
    "DEFAULT_POINTER_PATH",
    "DEFAULT_RELEASE_PREFIX_TEMPLATE",
    "IR_CONFIG_MANIFEST_SCHEMA",
    "IR_P4_EVIDENCE_SCHEMA",
    "IR_PUBLICATION_POLICY_SCHEMA",
    "IR_RELEASE_PACKAGE_SCHEMA",
    "IR_RELEASE_PRODUCER",
    "IR_RELEASE_ROOT_SCHEMA",
    "IRPublicationPolicy",
    "IRReleaseError",
    "IRReleasePackage",
    "P1_CONFIGS",
    "P4_EVIDENCE_KEYS",
    "QualifiedReleaseInputs",
    "build_p4_evidence",
    "default_releases_data_dir",
    "load_publication_policy",
    "load_qualified_inputs",
    "package_from_official_recipe",
    "package_ir_release",
    "render_checkpoint_card",
    "render_dataset_card",
    "validate_ir_release_package",
]
