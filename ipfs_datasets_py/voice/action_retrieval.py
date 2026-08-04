"""Abby-aware content-plane action proposal retrieval (VOICE-ACTION-008).

Projects slotted-DAG routes (and optional GraphRAG grounded plans) into
authority-free :class:`ActionProposalCandidate` records.  Retrieval may only
*propose* catalog-referenced logical actions; it never executes adapters,
never invents descriptors from free-text transcripts, and never embeds
executable locators.

Dual-plane rule (content plane only)::

    route + action-link map + optional template/evidence
      -> ActionProposalCandidate | explicit no_action
    authority plane (catalog / policy / confirmation / adapter)
      -> ActionDecision / ActionReceipt  (out of scope here)

Symbolic route maps are authoritative.  Embeddings, transcript keywords, and
model free-text may rank or attach evidence but cannot widen the catalog or
smuggle command/argv/url/import_path fields.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .action_links import (
    ACTION_LINK_SCHEMA,
    FORBIDDEN_CONTENT_FIELDS,
    NO_ACTION,
    ActionLink,
    ActionLinkDocument,
    ActionLinkSchemaError,
    content_digest,
    parse_action_link_document,
    reject_forbidden_content_fields,
)

# Public schema identity.
RETRIEVAL_SCHEMA: Final = "voice-action/action-retrieval@1"
RETRIEVAL_SCHEMA_VERSION: Final = "abby_action_retrieval_v1"
RETRIEVAL_DOC_PATH: Final = "docs/voice_action_dag/RETRIEVAL.md"
RETRIEVAL_SOURCE: Final = "abby_action_retrieval"

# Default on-disk projection produced by VOICE-ACTION-005.
DEFAULT_ACTION_LINKS_REL: Final = (
    "docs/phone_dialog_generation/slotted_response_action_links.json"
)

# Outcome kinds for a single retrieval turn.
OUTCOME_PROPOSAL: Final = "proposal"
OUTCOME_NO_ACTION: Final = "no_action"

# Align with action_links / action_runtime.contracts banned argument keys.
_BANNED_ARGUMENT_KEYS: Final = frozenset(
    {
        "command",
        "argv",
        "executable",
        "cwd",
        "env",
        "shell",
        "import",
        "import_path",
        "url",
        "credentials",
        "secret",
        "webhook",
    }
)

_ROUTE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DESCRIPTOR_INJECTION_RE = re.compile(
    r"(?i)\b(?:descriptor[_-]?id|logical[_-]?action)\s*[:=]\s*"
    r"([A-Za-z0-9][A-Za-z0-9._:/-]{0,255})"
)
_PATH_SUFFIX = "_path"

# Content-plane descriptor references for projection logical actions that the
# pilot voice_bridge historically used.  These are *references only*; authority
# plane catalog binding (VOICE-ACTION-009+) remains deployment-owned.
DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF: Final[Mapping[str, str]] = MappingProxyType(
    {
        "open_app_surface": "voice.ref.open_app_surface.v1",
        "open_wallet_documents": "voice.ref.open_wallet_documents.v1",
        "open_calendar_support": "voice.ref.open_calendar_support.v1",
        "review_service_interaction": "voice.ref.review_service_interaction.v1",
        "provide_provider_contact": "voice.ref.provide_provider_contact.v1",
        "open_service_detail": "voice.ref.open_service_detail.v1",
        "handoff_live_agent": "voice.ref.handoff_live_agent.v1",
        "escalate_safety": "voice.ref.escalate_safety.v1",
        # Pilot catalog 211ai-pilot-v1 logical actions (subset overlap).
        "read_calendar": "voice.python.read_calendar.v1",
        "create_calendar_reminder": "voice.python.create_calendar_reminder.v1",
        "read_provider_messages": "voice.python.read_provider_messages.v1",
        "leave_provider_message": "voice.python.leave_provider_message.v1",
        "schedule_service_callback": "voice.workflow.schedule_service_callback.v1",
    }
)


class ActionRetrievalError(ValueError):
    """Raised when retrieval inputs violate the content-plane contract."""

    def __init__(self, errors: str | Iterable[str]):
        if isinstance(errors, str):
            self.errors: tuple[str, ...] = (errors,)
        else:
            self.errors = tuple(str(item) for item in errors)
        detail = "; ".join(self.errors) or "invalid action retrieval input"
        super().__init__(f"{RETRIEVAL_SCHEMA}: {detail}")


def _text(value: Any, *, field_name: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise ActionRetrievalError(f"{field_name} must not be empty")
        return ""
    if not isinstance(value, str):
        raise ActionRetrievalError(f"{field_name} must be a string")
    result = value.strip()
    if required and not result:
        raise ActionRetrievalError(f"{field_name} must not be empty")
    return result


def _optional_safe_id(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field_name=field_name, required=False)
    if not text:
        return None
    if not _SAFE_ID_RE.fullmatch(text):
        raise ActionRetrievalError(
            f"{field_name} must match the safe content id pattern"
        )
    return text


def _clamp_confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ActionRetrievalError("confidence must be a finite number") from exc
    if score != score or score in (float("inf"), float("-inf")):
        raise ActionRetrievalError("confidence must be a finite number")
    return max(0.0, min(1.0, score))


def _normalize_route(value: Any) -> str:
    route = _text(value, field_name="route")
    if not _ROUTE_RE.fullmatch(route):
        raise ActionRetrievalError(
            "route must be a lower_snake slotted-DAG route id"
        )
    return route


def transcript_digest(transcript: str | None) -> str:
    """Return a full SHA-256 of the transcript (never used as authority)."""

    return sha256((transcript or "").encode("utf-8")).hexdigest()


def evidence_digest(evidence: Sequence[str] | None) -> str:
    """Return a stable digest of ordered, de-duplicated evidence ids/cids."""

    return content_digest(list(_normalize_evidence(evidence)))


def _normalize_evidence(evidence: Sequence[str] | None) -> tuple[str, ...]:
    if evidence is None:
        return ()
    if isinstance(evidence, str):
        evidence = (evidence,)
    if not isinstance(evidence, Sequence) or isinstance(
        evidence, (bytes, bytearray)
    ):
        raise ActionRetrievalError("evidence must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(evidence):
        item = _text(raw, field_name=f"evidence[{index}]")
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _normalize_string_map(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ActionRetrievalError(f"{field_name} must be a mapping")
    result: dict[str, str] = {}
    for raw_key, raw_val in value.items():
        key = _text(raw_key, field_name=f"{field_name}.key")
        lowered = key.casefold()
        if lowered in _BANNED_ARGUMENT_KEYS or lowered in FORBIDDEN_CONTENT_FIELDS:
            raise ActionRetrievalError(
                f"forbidden field {key!r} in {field_name}"
            )
        if lowered.endswith(_PATH_SUFFIX):
            raise ActionRetrievalError(
                f"forbidden path field {key!r} in {field_name}"
            )
        if not isinstance(raw_val, str):
            raise ActionRetrievalError(
                f"{field_name}.{key} must be a string"
            )
        result[key] = raw_val
    return MappingProxyType(result)


def _normalize_arguments(
    value: Mapping[str, Any] | None,
) -> Mapping[str, str]:
    """Normalize proposal arguments and reject executable smuggling."""

    return _normalize_string_map(value, field_name="arguments")


def stable_proposal_id(
    *,
    route: str,
    logical_action: str,
    template_id: str | None = None,
    evidence: Sequence[str] = (),
    descriptor_id: str | None = None,
) -> str:
    """Build a deterministic proposal id from content-plane fields only."""

    payload = {
        "descriptor_id": descriptor_id,
        "evidence": list(evidence),
        "logical_action": logical_action,
        "route": route,
        "schema": RETRIEVAL_SCHEMA,
        "template_id": template_id,
    }
    return f"prop-{content_digest(payload)[:16]}"


def extract_injection_claims(transcript: str | None) -> tuple[str, ...]:
    """Return descriptor/logical-action strings claimed inside free text.

    These claims are **ignored** for binding; the helper exists so tests and
    auditors can prove adversarial transcripts cannot invent descriptors.
    """

    if not transcript:
        return ()
    return tuple(
        match.group(1)
        for match in _DESCRIPTOR_INJECTION_RE.finditer(transcript)
    )


def _no_action_link(route: str) -> ActionLink:
    """Synthetic content-only link for missing / fail-closed routes."""

    return ActionLink(
        route=route,
        logical_action=NO_ACTION,
        classification="content-only",
        notes="fail-closed: unmapped or catalog-invalid route",
    )


@dataclass(frozen=True, slots=True)
class ActionProposalCandidate:
    """Authority-free action proposal candidate (content plane).

    Either a catalog-referenced logical action proposal, or an explicit
    ``no_action`` sentinel.  Never carries executables.
    """

    route: str
    logical_action: str
    classification: str
    outcome: str = OUTCOME_PROPOSAL
    proposal_id: str = ""
    descriptor_id: str | None = None
    template_id: str | None = None
    evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    arguments: Mapping[str, str] = field(default_factory=dict)
    confirmation_frame_id: str | None = None
    outcome_frame_ids: Mapping[str, str] = field(default_factory=dict)
    link_id: str | None = None
    source: str = RETRIEVAL_SOURCE
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        route = _normalize_route(self.route)
        logical_action = _text(self.logical_action, field_name="logical_action")
        classification = _text(self.classification, field_name="classification")
        outcome = _text(self.outcome, field_name="outcome")
        if outcome not in {OUTCOME_PROPOSAL, OUTCOME_NO_ACTION}:
            raise ActionRetrievalError(
                f"outcome must be {OUTCOME_PROPOSAL!r} or {OUTCOME_NO_ACTION!r}"
            )
        if outcome == OUTCOME_NO_ACTION or logical_action == NO_ACTION:
            logical_action = NO_ACTION
            outcome = OUTCOME_NO_ACTION
            descriptor_id = None
        else:
            if not _SAFE_ID_RE.fullmatch(logical_action):
                raise ActionRetrievalError(
                    "logical_action must match the safe content id pattern"
                )
            descriptor_id = _optional_safe_id(
                self.descriptor_id, field_name="descriptor_id"
            )

        template_id = _optional_safe_id(
            self.template_id, field_name="template_id"
        )
        evidence = _normalize_evidence(self.evidence)
        confidence = _clamp_confidence(self.confidence)
        arguments = _normalize_arguments(
            dict(self.arguments) if self.arguments is not None else None
        )
        confirmation = _optional_safe_id(
            self.confirmation_frame_id, field_name="confirmation_frame_id"
        )
        outcomes = _normalize_string_map(
            dict(self.outcome_frame_ids) if self.outcome_frame_ids else None,
            field_name="outcome_frame_ids",
        )
        link_id = _optional_safe_id(self.link_id, field_name="link_id")
        source = _text(self.source, field_name="source") or RETRIEVAL_SOURCE
        metadata = _normalize_string_map(
            dict(self.metadata) if self.metadata is not None else None,
            field_name="metadata",
        )

        # Always attach template_id and evidence digests when present.
        meta = dict(metadata)
        if template_id is not None:
            meta.setdefault("template_id", template_id)
        if evidence:
            meta.setdefault("evidence_digest", evidence_digest(evidence))
        meta.setdefault("retrieval_schema", RETRIEVAL_SCHEMA)
        meta.setdefault("retrieval_schema_version", RETRIEVAL_SCHEMA_VERSION)
        metadata = MappingProxyType(meta)

        try:
            reject_forbidden_content_fields(
                {
                    "route": route,
                    "logical_action": logical_action,
                    "arguments": dict(arguments),
                    "metadata": dict(metadata),
                }
            )
        except ActionLinkSchemaError as exc:
            raise ActionRetrievalError(str(exc)) from exc

        computed = stable_proposal_id(
            route=route,
            logical_action=logical_action,
            template_id=template_id,
            evidence=evidence,
            descriptor_id=descriptor_id,
        )
        proposal_id = (
            _text(self.proposal_id, field_name="proposal_id", required=False)
            or computed
        )
        if proposal_id != computed:
            # Allow empty-or-matching only; mismatch fails closed.
            raise ActionRetrievalError(
                "proposal_id does not match deterministic retrieval content"
            )

        object.__setattr__(self, "route", route)
        object.__setattr__(self, "logical_action", logical_action)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "proposal_id", proposal_id)
        object.__setattr__(self, "descriptor_id", descriptor_id)
        object.__setattr__(self, "template_id", template_id)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "confirmation_frame_id", confirmation)
        object.__setattr__(self, "outcome_frame_ids", outcomes)
        object.__setattr__(self, "link_id", link_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "metadata", metadata)

    @property
    def is_no_action(self) -> bool:
        return self.outcome == OUTCOME_NO_ACTION or self.logical_action == NO_ACTION

    @property
    def may_propose(self) -> bool:
        return not self.is_no_action and bool(self.logical_action)

    @property
    def is_catalog_bound(self) -> bool:
        return not self.is_no_action and bool(self.descriptor_id)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "arguments": dict(self.arguments),
            "classification": self.classification,
            "confidence": self.confidence,
            "confirmation_frame_id": self.confirmation_frame_id,
            "descriptor_id": self.descriptor_id,
            "evidence": list(self.evidence),
            "link_id": self.link_id,
            "logical_action": self.logical_action,
            "metadata": dict(self.metadata),
            "outcome": self.outcome,
            "outcome_frame_ids": dict(self.outcome_frame_ids),
            "proposal_id": self.proposal_id,
            "route": self.route,
            "source": self.source,
            "template_id": self.template_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self.identity_dict())

    def content_digest(self) -> str:
        return content_digest(self.identity_dict())


@dataclass(frozen=True, slots=True)
class ActionRetrievalResult:
    """One retrieval turn: zero-or-more candidates plus provenance digests."""

    route: str
    candidates: tuple[ActionProposalCandidate, ...]
    transcript_digest: str = ""
    primary: ActionProposalCandidate | None = None
    grounded_response: Mapping[str, Any] | None = None
    source: str = RETRIEVAL_SOURCE
    schema: str = RETRIEVAL_SCHEMA
    schema_version: str = RETRIEVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        route = _normalize_route(self.route)
        if not isinstance(self.candidates, tuple):
            candidates = tuple(self.candidates or ())
        else:
            candidates = self.candidates
        for index, item in enumerate(candidates):
            if not isinstance(item, ActionProposalCandidate):
                raise ActionRetrievalError(
                    f"candidates[{index}] must be an ActionProposalCandidate"
                )
        primary = self.primary
        if primary is None and candidates:
            primary = candidates[0]
        if primary is not None and not isinstance(primary, ActionProposalCandidate):
            raise ActionRetrievalError("primary must be an ActionProposalCandidate")
        digest = self.transcript_digest or ""
        if digest and (
            len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise ActionRetrievalError(
                "transcript_digest must be a lower-case sha256 hex digest"
            )
        grounded = None
        if self.grounded_response is not None:
            if not isinstance(self.grounded_response, Mapping):
                raise ActionRetrievalError(
                    "grounded_response must be a mapping when provided"
                )
            # Never allow executable smuggling via grounded plan metadata.
            try:
                reject_forbidden_content_fields(dict(self.grounded_response))
            except ActionLinkSchemaError as exc:
                raise ActionRetrievalError(str(exc)) from exc
            grounded = MappingProxyType(dict(self.grounded_response))

        object.__setattr__(self, "route", route)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "transcript_digest", digest)
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "grounded_response", grounded)
        object.__setattr__(
            self, "source", _text(self.source, field_name="source") or RETRIEVAL_SOURCE
        )
        object.__setattr__(self, "schema", RETRIEVAL_SCHEMA)
        object.__setattr__(self, "schema_version", RETRIEVAL_SCHEMA_VERSION)

    @property
    def is_no_action(self) -> bool:
        if not self.candidates:
            return True
        return all(item.is_no_action for item in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "grounded_response": (
                dict(self.grounded_response) if self.grounded_response else None
            ),
            "is_no_action": self.is_no_action,
            "primary": self.primary.to_dict() if self.primary else None,
            "route": self.route,
            "schema": self.schema,
            "schema_version": self.schema_version,
            "source": self.source,
            "transcript_digest": self.transcript_digest,
        }


def _repo_root_from_here() -> Path:
    # .../ipfs_datasets_py/ipfs_datasets_py/voice/action_retrieval.py
    # parents[3] == monorepo root when nested under ipfs_datasets_py/.
    here = Path(__file__).resolve()
    candidates = (
        here.parents[3],  # monorepo root
        here.parents[2],  # ipfs_datasets_py package root (fallback)
        Path.cwd(),
    )
    for root in candidates:
        if (root / DEFAULT_ACTION_LINKS_REL).is_file():
            return root
        if (root / "docs" / "phone_dialog_generation").is_dir():
            return root
    return candidates[0]


def default_action_links_path(repo_root: Path | None = None) -> Path:
    """Return the default slotted-response action-link projection path."""

    root = repo_root if repo_root is not None else _repo_root_from_here()
    return Path(root) / DEFAULT_ACTION_LINKS_REL


def load_action_link_document(
    path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
) -> ActionLinkDocument:
    """Load and validate the action-link projection document (fail closed)."""

    target = Path(path) if path is not None else default_action_links_path(repo_root)
    if not target.is_file():
        raise ActionRetrievalError(f"missing action-link projection: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActionRetrievalError(
            f"failed to read action-link projection: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ActionRetrievalError("action-link projection root must be an object")
    try:
        return parse_action_link_document(payload)
    except ActionLinkSchemaError as exc:
        raise ActionRetrievalError(str(exc)) from exc


def _evidence_from_grounded_plan(
    plan: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not plan:
        return ()
    collected: list[str] = []
    sources = plan.get("sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        for item in sources:
            if isinstance(item, Mapping):
                cid = item.get("cid") or item.get("source_cid")
                if cid:
                    collected.append(str(cid))
            elif isinstance(item, str) and item.strip():
                collected.append(item.strip())
    metadata = plan.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("template_source_cids", "source_cids", "evidence_cids"):
            raw = metadata.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                for item in raw:
                    if item:
                        collected.append(str(item))
        for key in ("index_cid", "graph_cid", "template_content_sha256"):
            raw = metadata.get(key)
            if raw:
                collected.append(str(raw))
    return _normalize_evidence(collected)


def _template_id_from_plan(plan: Mapping[str, Any] | None) -> str | None:
    if not plan:
        return None
    raw = plan.get("template_id")
    if raw is None and isinstance(plan.get("metadata"), Mapping):
        raw = plan["metadata"].get("template_id")
    if raw is None:
        return None
    return _optional_safe_id(str(raw), field_name="template_id")


def _confidence_from_plan(
    plan: Mapping[str, Any] | None,
    fallback: float,
) -> float:
    if plan is None:
        return _clamp_confidence(fallback)
    if "confidence" in plan:
        return _clamp_confidence(plan.get("confidence"))
    return _clamp_confidence(fallback)


@dataclass
class ActionProposalRetriever:
    """Symbolic (route-map) action proposal retriever.

    The route → logical_action map from an :class:`ActionLinkDocument` is the
    sole authority for which action may be proposed.  Optional catalog maps
    only *restrict* proposals (fail closed to ``no_action``); they never add
    new logical actions from free text.
    """

    action_links: ActionLinkDocument
    descriptor_map: Mapping[str, str] = field(
        default_factory=lambda: dict(DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF)
    )
    allowed_logical_actions: frozenset[str] | None = None
    require_catalog_entry: bool = False
    source: str = RETRIEVAL_SOURCE

    def __post_init__(self) -> None:
        if not isinstance(self.action_links, ActionLinkDocument):
            raise TypeError("action_links must be an ActionLinkDocument")
        descriptor_map = {
            str(k): str(v) for k, v in dict(self.descriptor_map or {}).items()
        }
        for key, value in descriptor_map.items():
            if not _SAFE_ID_RE.fullmatch(key):
                raise ActionRetrievalError(
                    f"descriptor_map logical_action {key!r} is invalid"
                )
            if not _SAFE_ID_RE.fullmatch(value):
                raise ActionRetrievalError(
                    f"descriptor_map descriptor_id {value!r} is invalid"
                )
        object.__setattr__(self, "descriptor_map", MappingProxyType(descriptor_map))
        if self.allowed_logical_actions is not None:
            object.__setattr__(
                self,
                "allowed_logical_actions",
                frozenset(str(item) for item in self.allowed_logical_actions),
            )
        object.__setattr__(
            self,
            "source",
            _text(self.source, field_name="source") or RETRIEVAL_SOURCE,
        )

    @classmethod
    def from_action_links_path(
        cls,
        path: str | Path | None = None,
        *,
        repo_root: Path | None = None,
        descriptor_map: Mapping[str, str] | None = None,
        allowed_logical_actions: Iterable[str] | None = None,
        require_catalog_entry: bool = False,
        source: str = RETRIEVAL_SOURCE,
    ) -> ActionProposalRetriever:
        document = load_action_link_document(path, repo_root=repo_root)
        return cls(
            action_links=document,
            descriptor_map=(
                dict(descriptor_map)
                if descriptor_map is not None
                else dict(DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF)
            ),
            allowed_logical_actions=(
                frozenset(allowed_logical_actions)
                if allowed_logical_actions is not None
                else None
            ),
            require_catalog_entry=require_catalog_entry,
            source=source,
        )

    @classmethod
    def from_links(
        cls,
        links: Sequence[ActionLink | Mapping[str, Any]],
        *,
        source: str = "inline-action-links",
        descriptor_map: Mapping[str, str] | None = None,
        allowed_logical_actions: Iterable[str] | None = None,
        require_catalog_entry: bool = False,
    ) -> ActionProposalRetriever:
        document = ActionLinkDocument(links=tuple(links), source=source)
        return cls(
            action_links=document,
            descriptor_map=(
                dict(descriptor_map)
                if descriptor_map is not None
                else dict(DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF)
            ),
            allowed_logical_actions=(
                frozenset(allowed_logical_actions)
                if allowed_logical_actions is not None
                else None
            ),
            require_catalog_entry=require_catalog_entry,
            source=RETRIEVAL_SOURCE,
        )

    def link_for(self, route: str) -> ActionLink:
        """Return the action link for *route*, or a synthetic no_action link."""

        normalized = _normalize_route(route)
        link = self.action_links.by_route().get(normalized)
        if link is None:
            return _no_action_link(normalized)
        return link

    def routes(self) -> tuple[str, ...]:
        return tuple(link.route for link in self.action_links.links)

    def _catalog_allows(self, logical_action: str) -> bool:
        if logical_action == NO_ACTION:
            return True
        if self.allowed_logical_actions is not None:
            if logical_action not in self.allowed_logical_actions:
                return False
        if self.require_catalog_entry:
            return logical_action in self.descriptor_map
        return True

    def _descriptor_for(self, logical_action: str) -> str | None:
        if logical_action == NO_ACTION:
            return None
        return self.descriptor_map.get(logical_action)

    def propose_from_route(
        self,
        route: str,
        *,
        transcript: str = "",
        template_id: str | None = None,
        evidence: Sequence[str] | None = None,
        confidence: float = 0.0,
        arguments: Mapping[str, str] | None = None,
        # Non-authoritative hints (ignored for binding):
        suggested_logical_action: str | None = None,
        suggested_descriptor_id: str | None = None,
    ) -> ActionProposalCandidate:
        """Map a slotted-DAG route to a proposal candidate or no_action.

        *transcript*, *suggested_logical_action*, and *suggested_descriptor_id*
        are intentionally non-authoritative.  Adversarial free text cannot
        invent descriptors or widen the catalog.
        """

        # Consume non-authoritative inputs so injection claims are measurable
        # but never used for binding.
        _ = extract_injection_claims(transcript)
        _ = suggested_logical_action
        _ = suggested_descriptor_id

        link = self.link_for(route)
        evidence_ids = _normalize_evidence(evidence)
        # Link-level evidence cids (content plane) append after call-site evidence.
        if link.evidence_cids:
            evidence_ids = _normalize_evidence(
                list(evidence_ids) + list(link.evidence_cids)
            )
        safe_template = _optional_safe_id(template_id, field_name="template_id")
        safe_args = _normalize_arguments(arguments)
        score = _clamp_confidence(confidence)

        logical_action = link.logical_action
        classification = link.classification

        if not link.may_propose or logical_action == NO_ACTION:
            return ActionProposalCandidate(
                route=link.route,
                logical_action=NO_ACTION,
                classification="content-only",
                outcome=OUTCOME_NO_ACTION,
                template_id=safe_template,
                evidence=evidence_ids,
                confidence=score,
                arguments={},
                confirmation_frame_id=None,
                outcome_frame_ids={},
                link_id=link.link_id,
                source=self.source,
                metadata={
                    "reason": "content_only_or_no_action",
                    "link_classification": classification,
                },
            )

        if not self._catalog_allows(logical_action):
            return ActionProposalCandidate(
                route=link.route,
                logical_action=NO_ACTION,
                classification="content-only",
                outcome=OUTCOME_NO_ACTION,
                template_id=safe_template,
                evidence=evidence_ids,
                confidence=score,
                arguments={},
                confirmation_frame_id=None,
                outcome_frame_ids={},
                link_id=link.link_id,
                source=self.source,
                metadata={
                    "reason": "catalog_reject",
                    "rejected_logical_action": logical_action,
                    "link_classification": classification,
                },
            )

        descriptor_id = self._descriptor_for(logical_action)
        if self.require_catalog_entry and not descriptor_id:
            return ActionProposalCandidate(
                route=link.route,
                logical_action=NO_ACTION,
                classification="content-only",
                outcome=OUTCOME_NO_ACTION,
                template_id=safe_template,
                evidence=evidence_ids,
                confidence=score,
                arguments={},
                link_id=link.link_id,
                source=self.source,
                metadata={
                    "reason": "missing_descriptor_binding",
                    "rejected_logical_action": logical_action,
                },
            )

        return ActionProposalCandidate(
            route=link.route,
            logical_action=logical_action,
            classification=classification,
            outcome=OUTCOME_PROPOSAL,
            descriptor_id=descriptor_id,
            template_id=safe_template,
            evidence=evidence_ids,
            confidence=score,
            arguments=safe_args,
            confirmation_frame_id=link.confirmation_frame_id,
            outcome_frame_ids=dict(link.outcome_frame_ids),
            link_id=link.link_id,
            source=self.source,
            metadata={
                "link_classification": classification,
                "action_link_schema": ACTION_LINK_SCHEMA,
            },
        )

    def retrieve(
        self,
        *,
        route: str,
        transcript: str = "",
        template_id: str | None = None,
        evidence: Sequence[str] | None = None,
        confidence: float = 0.0,
        arguments: Mapping[str, str] | None = None,
        grounded_response: Mapping[str, Any] | None = None,
        suggested_logical_action: str | None = None,
        suggested_descriptor_id: str | None = None,
    ) -> ActionRetrievalResult:
        """Retrieve proposal candidates for a classified route.

        When *grounded_response* is a GraphRAG plan dict, template id and
        evidence digests are taken from the plan when not supplied explicitly.
        Plan free-text never overrides the symbolic route map.
        """

        plan = grounded_response
        if plan is not None and not isinstance(plan, Mapping):
            raise ActionRetrievalError("grounded_response must be a mapping")

        resolved_template = template_id or _template_id_from_plan(plan)
        plan_evidence = _evidence_from_grounded_plan(plan)
        merged_evidence = _normalize_evidence(
            list(evidence or ()) + list(plan_evidence)
        )
        score = (
            _confidence_from_plan(plan, confidence)
            if plan is not None
            else _clamp_confidence(confidence)
        )

        candidate = self.propose_from_route(
            route,
            transcript=transcript,
            template_id=resolved_template,
            evidence=merged_evidence,
            confidence=score,
            arguments=arguments,
            suggested_logical_action=suggested_logical_action,
            suggested_descriptor_id=suggested_descriptor_id,
        )
        return ActionRetrievalResult(
            route=_normalize_route(route),
            candidates=(candidate,),
            transcript_digest=transcript_digest(transcript),
            primary=candidate,
            grounded_response=plan,
            source=self.source,
        )

    def sample_routes(
        self,
        routes: Sequence[str] | None = None,
        *,
        template_id_for: Mapping[str, str] | None = None,
        evidence_for: Mapping[str, Sequence[str]] | None = None,
        confidence: float = 0.75,
    ) -> tuple[ActionRetrievalResult, ...]:
        """Sample each configured route and return catalog-valid or no_action.

        Acceptance surface for VOICE-ACTION-008: every route yields either a
        catalog-valid proposal candidate or an explicit ``no_action``.
        """

        route_list = (
            tuple(routes) if routes is not None else self.routes()
        )
        templates = dict(template_id_for or {})
        evidence_map = {
            str(k): tuple(v) for k, v in dict(evidence_for or {}).items()
        }
        results: list[ActionRetrievalResult] = []
        for route in route_list:
            results.append(
                self.retrieve(
                    route=route,
                    template_id=templates.get(route),
                    evidence=evidence_map.get(route),
                    confidence=confidence,
                )
            )
        return tuple(results)


def retrieve_action_proposals(
    *,
    route: str,
    action_links: ActionLinkDocument | None = None,
    action_links_path: str | Path | None = None,
    transcript: str = "",
    template_id: str | None = None,
    evidence: Sequence[str] | None = None,
    confidence: float = 0.0,
    arguments: Mapping[str, str] | None = None,
    grounded_response: Mapping[str, Any] | None = None,
    descriptor_map: Mapping[str, str] | None = None,
    allowed_logical_actions: Iterable[str] | None = None,
    require_catalog_entry: bool = False,
    suggested_logical_action: str | None = None,
    suggested_descriptor_id: str | None = None,
) -> ActionRetrievalResult:
    """Functional API: retrieve action proposals for a single route.

    Loads the default slotted-DAG action-link projection when *action_links*
    is omitted.
    """

    if action_links is None:
        retriever = ActionProposalRetriever.from_action_links_path(
            action_links_path,
            descriptor_map=descriptor_map,
            allowed_logical_actions=allowed_logical_actions,
            require_catalog_entry=require_catalog_entry,
        )
    else:
        retriever = ActionProposalRetriever(
            action_links=action_links,
            descriptor_map=(
                dict(descriptor_map)
                if descriptor_map is not None
                else dict(DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF)
            ),
            allowed_logical_actions=(
                frozenset(allowed_logical_actions)
                if allowed_logical_actions is not None
                else None
            ),
            require_catalog_entry=require_catalog_entry,
        )
    return retriever.retrieve(
        route=route,
        transcript=transcript,
        template_id=template_id,
        evidence=evidence,
        confidence=confidence,
        arguments=arguments,
        grounded_response=grounded_response,
        suggested_logical_action=suggested_logical_action,
        suggested_descriptor_id=suggested_descriptor_id,
    )


def catalog_valid_or_no_action(
    result: ActionRetrievalResult | ActionProposalCandidate,
    *,
    allowed_logical_actions: Iterable[str] | None = None,
    descriptor_map: Mapping[str, str] | None = None,
) -> bool:
    """Return True when *result* is an explicit no_action or catalog-valid.

    Catalog validity means:
    - ``logical_action`` is in *allowed_logical_actions* (when provided); and
    - when a *descriptor_map* is provided, ``descriptor_id`` matches the map
      entry for that logical action.
    """

    if isinstance(result, ActionRetrievalResult):
        if not result.candidates:
            return True
        return all(
            catalog_valid_or_no_action(
                item,
                allowed_logical_actions=allowed_logical_actions,
                descriptor_map=descriptor_map,
            )
            for item in result.candidates
        )

    candidate = result
    if candidate.is_no_action:
        return True
    if allowed_logical_actions is not None:
        allowed = frozenset(str(item) for item in allowed_logical_actions)
        if candidate.logical_action not in allowed:
            return False
    if descriptor_map is not None:
        expected = descriptor_map.get(candidate.logical_action)
        if expected is None:
            return False
        if candidate.descriptor_id != expected:
            return False
    # Free-text must never have produced forbidden argument keys (constructor
    # already rejects them); re-check for defense in depth.
    try:
        reject_forbidden_content_fields(dict(candidate.arguments))
        reject_forbidden_content_fields(dict(candidate.metadata))
    except ActionLinkSchemaError:
        return False
    return True


__all__ = [
    "DEFAULT_ACTION_LINKS_REL",
    "DEFAULT_LOGICAL_ACTION_TO_DESCRIPTOR_REF",
    "OUTCOME_NO_ACTION",
    "OUTCOME_PROPOSAL",
    "RETRIEVAL_DOC_PATH",
    "RETRIEVAL_SCHEMA",
    "RETRIEVAL_SCHEMA_VERSION",
    "RETRIEVAL_SOURCE",
    "ActionProposalCandidate",
    "ActionProposalRetriever",
    "ActionRetrievalError",
    "ActionRetrievalResult",
    "catalog_valid_or_no_action",
    "default_action_links_path",
    "evidence_digest",
    "extract_injection_claims",
    "load_action_link_document",
    "retrieve_action_proposals",
    "stable_proposal_id",
    "transcript_digest",
]
