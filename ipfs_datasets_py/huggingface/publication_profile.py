"""Parameterized append-only Hugging Face publication profiles.

A :class:`HuggingFacePublicationProfile` binds program/goal/schema identity,
repository layout, release prefix, pointer path, revision, and commit message
for one publication program without weakening the shared append-only contract:

* prohibited operations are always a **superset** of the base refuse set;
* dry-run planning never contacts write endpoints;
* pointer promotion waits for successful pinned redownload validation;
* patent/legal profiles never embed unrelated program schema strings
  (for example Abby-voice plan/receipt/release schemas).

Legacy Abby defaults remain available as :func:`abby_voice_publication_profile`
and continue to use the historical schema strings and repository layout.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final

# Shared refuse set.  Every profile must include at least these labels; profiles
# may only add further prohibitions.
BASE_PROHIBITED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "delete",
        "deletefile",
        "deletefolder",
        "move",
        "copy",
        "overwrite_legacy",
        "force_push",
        "rewrite_main",
    }
)

# Historical Abby wire identities (byte/wire compatible with pre-generalization).
ABBY_VOICE_PROFILE_ID: Final = "abby-voice"
ABBY_VOICE_PROGRAM_ID: Final = "abby-voice"
ABBY_VOICE_GOAL_ID: Final = "ABBY-VOICE-G021"
ABBY_VOICE_PLAN_SCHEMA: Final = "abby-voice-hf-publication-plan/v1"
ABBY_VOICE_RECEIPT_SCHEMA: Final = "abby-voice-hf-publication-receipt/v1"
ABBY_VOICE_CANONICAL_RELEASE_SCHEMA: Final = "abby-voice-huggingface-release/v1"
ABBY_VOICE_DEFAULT_REPOSITORY_ID: Final = "Publicus/211-abby-tts"
ABBY_VOICE_RELEASE_PREFIX_TEMPLATE: Final = "data/abby_voice_v2/{release_id}"
ABBY_VOICE_POINTER_PATH: Final = "runtime/abby_voice_release_pointer.json"
ABBY_VOICE_COMMIT_MESSAGE: Final = "abby-voice: append-only immutable release"

# Patent / legal (JusticeDAO) program identities — no Abby schema strings.
PATENT_LEGAL_PROFILE_ID: Final = "patent-legal"
PATENT_LEGAL_PROGRAM_ID: Final = "patent-legal-intelligence"
PATENT_LEGAL_GOAL_ID: Final = "PATLAW-G100"
PATENT_LEGAL_PLAN_SCHEMA: Final = "patent-legal-hf-publication-plan/v1"
PATENT_LEGAL_RECEIPT_SCHEMA: Final = "patent-legal-hf-publication-receipt/v1"
PATENT_LEGAL_CANONICAL_RELEASE_SCHEMA: Final = "patent-legal-huggingface-release/v1"
PATENT_LEGAL_DEFAULT_REPOSITORY_ID: Final = "JusticeDAO/patent-legal-public"
PATENT_LEGAL_RELEASE_PREFIX_TEMPLATE: Final = "data/patent_legal/{release_id}"
PATENT_LEGAL_POINTER_PATH: Final = "runtime/patent_legal_release_pointer.json"
PATENT_LEGAL_COMMIT_MESSAGE: Final = (
    "patent-legal: append-only immutable public release"
)

DEFAULT_TARGET_REVISION: Final = "main"
DEFAULT_REPOSITORY_TYPE: Final = "dataset"

# Substrings that patent/legal profiles must not embed (unrelated programs).
_UNRELATED_PROGRAM_MARKERS: Final[tuple[str, ...]] = (
    "abby-voice",
    "abby_voice",
    "abby-tts",
    "ABBY-VOICE",
)

_KNOWN_PLAN_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        ABBY_VOICE_PLAN_SCHEMA,
        PATENT_LEGAL_PLAN_SCHEMA,
    }
)
_KNOWN_RECEIPT_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        ABBY_VOICE_RECEIPT_SCHEMA,
        PATENT_LEGAL_RECEIPT_SCHEMA,
    }
)


class PublicationProfileError(ValueError):
    """Raised when a publication profile is incomplete or weakens the contract."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PublicationProfileError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise PublicationProfileError(f"{label} must not contain NUL")
    return value


def _normalize_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise PublicationProfileError(f"unsafe relative path: {value!r}")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts or not parts:
        raise PublicationProfileError(f"unsafe relative path: {value!r}")
    return "/".join(parts)


def _normalize_prohibited(operations: Iterable[str]) -> frozenset[str]:
    normalized = frozenset(
        str(item).strip().casefold()
        for item in operations
        if str(item).strip()
    )
    if not BASE_PROHIBITED_OPERATIONS.issubset(normalized):
        missing = sorted(BASE_PROHIBITED_OPERATIONS - normalized)
        raise PublicationProfileError(
            "publication profile weakens prohibited operations; missing: "
            + ", ".join(missing)
        )
    return frozenset(sorted(normalized))


def _assert_no_unrelated_program_strings(
    *,
    profile_id: str,
    fields: Mapping[str, str],
) -> None:
    """Patent/legal (and any non-Abby) profiles must not carry Abby schema strings."""

    if profile_id == ABBY_VOICE_PROFILE_ID or profile_id.startswith("abby"):
        return
    offenders: list[str] = []
    for field_name, value in fields.items():
        lowered = value.casefold()
        for marker in _UNRELATED_PROGRAM_MARKERS:
            if marker.casefold() in lowered:
                offenders.append(f"{field_name} contains {marker!r}")
    if offenders:
        raise PublicationProfileError(
            "patent/legal publication profile contains unrelated program "
            "schema strings: " + "; ".join(sorted(offenders))
        )


@dataclass(frozen=True, slots=True)
class HuggingFacePublicationProfile:
    """Program-bound parameters for the append-only Hugging Face publisher.

    Profiles parameterize identity and layout only.  They cannot disable
    add-only planning, shrink the prohibited-operation set, skip dry-run
    isolation, or promote a pointer before pinned redownload validation.
    """

    profile_id: str
    program_id: str
    goal_id: str
    plan_schema_version: str
    receipt_schema_version: str
    repository_id: str
    release_prefix_template: str
    pointer_path: str
    repository_type: str = DEFAULT_REPOSITORY_TYPE
    target_revision: str = DEFAULT_TARGET_REVISION
    commit_message: str = "append-only immutable release"
    canonical_release_schema: str = ""
    prohibited_operations: frozenset[str] = field(
        default_factory=lambda: frozenset(BASE_PROHIBITED_OPERATIONS)
    )
    require_pinned_verification_before_promotion: bool = True
    allow_remote_write_on_dry_run: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        profile_id = _text(self.profile_id, label="profile_id")
        program_id = _text(self.program_id, label="program_id")
        goal_id = _text(self.goal_id, label="goal_id")
        plan_schema = _text(self.plan_schema_version, label="plan_schema_version")
        receipt_schema = _text(
            self.receipt_schema_version, label="receipt_schema_version"
        )
        repository_id = _text(self.repository_id, label="repository_id")
        repo_type = _text(self.repository_type, label="repository_type").casefold()
        if repo_type not in {"dataset", "model", "space"}:
            raise PublicationProfileError(
                "repository_type must be dataset, model, or space"
            )
        template = _text(
            self.release_prefix_template, label="release_prefix_template"
        )
        if "{release_id}" not in template:
            raise PublicationProfileError(
                "release_prefix_template must include {release_id}"
            )
        pointer_path = _normalize_relative_path(self.pointer_path)
        target_revision = _text(self.target_revision, label="target_revision")
        if target_revision != DEFAULT_TARGET_REVISION:
            raise PublicationProfileError(
                "immutable publication currently supports target_revision=main only"
            )
        commit_message = _text(self.commit_message, label="commit_message")
        canonical = str(self.canonical_release_schema or "").strip()
        if canonical:
            canonical = _text(canonical, label="canonical_release_schema")

        prohibited = _normalize_prohibited(self.prohibited_operations)

        if self.allow_remote_write_on_dry_run:
            raise PublicationProfileError(
                "publication profiles must not allow remote writes during dry run"
            )
        if not self.require_pinned_verification_before_promotion:
            raise PublicationProfileError(
                "publication profiles must require pinned verification before "
                "pointer promotion"
            )

        if plan_schema not in _KNOWN_PLAN_SCHEMAS:
            # Allow forward-compatible program schemas that follow the naming
            # convention without registering each one in this module.
            if not (
                plan_schema.endswith("-hf-publication-plan/v1")
                and "hf-publication-plan" in plan_schema
            ):
                raise PublicationProfileError(
                    f"unsupported plan_schema_version: {plan_schema}"
                )
        if receipt_schema not in _KNOWN_RECEIPT_SCHEMAS:
            if not (
                receipt_schema.endswith("-hf-publication-receipt/v1")
                and "hf-publication-receipt" in receipt_schema
            ):
                raise PublicationProfileError(
                    f"unsupported receipt_schema_version: {receipt_schema}"
                )

        identity_fields = {
            "profile_id": profile_id,
            "program_id": program_id,
            "goal_id": goal_id,
            "plan_schema_version": plan_schema,
            "receipt_schema_version": receipt_schema,
            "canonical_release_schema": canonical,
            "release_prefix_template": template,
            "pointer_path": pointer_path,
            "commit_message": commit_message,
            "repository_id": repository_id,
        }
        _assert_no_unrelated_program_strings(
            profile_id=profile_id,
            fields=identity_fields,
        )

        metadata = dict(self.metadata or {})
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "program_id", program_id)
        object.__setattr__(self, "goal_id", goal_id)
        object.__setattr__(self, "plan_schema_version", plan_schema)
        object.__setattr__(self, "receipt_schema_version", receipt_schema)
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(self, "repository_type", repo_type)
        object.__setattr__(self, "release_prefix_template", template)
        object.__setattr__(self, "pointer_path", pointer_path)
        object.__setattr__(self, "target_revision", target_revision)
        object.__setattr__(self, "commit_message", commit_message)
        object.__setattr__(self, "canonical_release_schema", canonical)
        object.__setattr__(self, "prohibited_operations", prohibited)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "require_pinned_verification_before_promotion", True)
        object.__setattr__(self, "allow_remote_write_on_dry_run", False)

    def release_prefix_for(self, release_id: str) -> str:
        safe = str(release_id or "").strip()
        if (
            not safe
            or "/" in safe
            or "\\" in safe
            or ".." in safe
            or safe.startswith(".")
        ):
            raise PublicationProfileError(f"unsafe release_id: {release_id!r}")
        return _normalize_relative_path(
            self.release_prefix_template.format(release_id=safe)
        )

    def with_repository(self, repository_id: str) -> HuggingFacePublicationProfile:
        """Return a copy bound to a different repository id (same program)."""

        return replace(self, repository_id=_text(repository_id, label="repository_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_remote_write_on_dry_run": False,
            "canonical_release_schema": self.canonical_release_schema or None,
            "commit_message": self.commit_message,
            "goal_id": self.goal_id,
            "metadata": dict(self.metadata),
            "plan_schema_version": self.plan_schema_version,
            "pointer_path": self.pointer_path,
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "prohibited_operations": sorted(self.prohibited_operations),
            "receipt_schema_version": self.receipt_schema_version,
            "release_prefix_template": self.release_prefix_template,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "require_pinned_verification_before_promotion": True,
            "target_revision": self.target_revision,
        }


def abby_voice_publication_profile(
    *,
    repository_id: str = ABBY_VOICE_DEFAULT_REPOSITORY_ID,
) -> HuggingFacePublicationProfile:
    """Legacy Abby voice profile (wire-compatible schema and layout defaults)."""

    return HuggingFacePublicationProfile(
        profile_id=ABBY_VOICE_PROFILE_ID,
        program_id=ABBY_VOICE_PROGRAM_ID,
        goal_id=ABBY_VOICE_GOAL_ID,
        plan_schema_version=ABBY_VOICE_PLAN_SCHEMA,
        receipt_schema_version=ABBY_VOICE_RECEIPT_SCHEMA,
        canonical_release_schema=ABBY_VOICE_CANONICAL_RELEASE_SCHEMA,
        repository_id=repository_id,
        repository_type=DEFAULT_REPOSITORY_TYPE,
        release_prefix_template=ABBY_VOICE_RELEASE_PREFIX_TEMPLATE,
        pointer_path=ABBY_VOICE_POINTER_PATH,
        target_revision=DEFAULT_TARGET_REVISION,
        commit_message=ABBY_VOICE_COMMIT_MESSAGE,
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
        require_pinned_verification_before_promotion=True,
        allow_remote_write_on_dry_run=False,
        metadata={
            "legacy_profile": True,
            "program": "abby-voice",
        },
    )


def patent_legal_publication_profile(
    *,
    repository_id: str = PATENT_LEGAL_DEFAULT_REPOSITORY_ID,
    goal_id: str = PATENT_LEGAL_GOAL_ID,
) -> HuggingFacePublicationProfile:
    """JusticeDAO patent/legal public-release profile (no Abby schema strings)."""

    return HuggingFacePublicationProfile(
        profile_id=PATENT_LEGAL_PROFILE_ID,
        program_id=PATENT_LEGAL_PROGRAM_ID,
        goal_id=goal_id,
        plan_schema_version=PATENT_LEGAL_PLAN_SCHEMA,
        receipt_schema_version=PATENT_LEGAL_RECEIPT_SCHEMA,
        canonical_release_schema=PATENT_LEGAL_CANONICAL_RELEASE_SCHEMA,
        repository_id=repository_id,
        repository_type=DEFAULT_REPOSITORY_TYPE,
        release_prefix_template=PATENT_LEGAL_RELEASE_PREFIX_TEMPLATE,
        pointer_path=PATENT_LEGAL_POINTER_PATH,
        target_revision=DEFAULT_TARGET_REVISION,
        commit_message=PATENT_LEGAL_COMMIT_MESSAGE,
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
        require_pinned_verification_before_promotion=True,
        allow_remote_write_on_dry_run=False,
        metadata={
            "legacy_profile": False,
            "program": "patent-legal-intelligence",
            "track": "public-publication",
        },
    )


def get_publication_profile(
    profile_id: str,
    *,
    repository_id: str | None = None,
) -> HuggingFacePublicationProfile:
    """Resolve a built-in profile by id."""

    key = _text(profile_id, label="profile_id").casefold()
    if key in {ABBY_VOICE_PROFILE_ID, "abby", "abby_voice", "abby-voice-g021"}:
        if repository_id is None:
            return abby_voice_publication_profile()
        return abby_voice_publication_profile(repository_id=repository_id)
    if key in {
        PATENT_LEGAL_PROFILE_ID,
        "patent",
        "legal",
        "justicedao",
        "justice-dao",
        "patlaw",
        "patlaw-g100",
    }:
        if repository_id is None:
            return patent_legal_publication_profile()
        return patent_legal_publication_profile(repository_id=repository_id)
    raise PublicationProfileError(f"unknown publication profile_id: {profile_id!r}")


def is_known_plan_schema(schema_version: str) -> bool:
    text = str(schema_version or "").strip()
    if text in _KNOWN_PLAN_SCHEMAS:
        return True
    return bool(
        text.endswith("-hf-publication-plan/v1") and "hf-publication-plan" in text
    )


def is_known_receipt_schema(schema_version: str) -> bool:
    text = str(schema_version or "").strip()
    if text in _KNOWN_RECEIPT_SCHEMAS:
        return True
    return bool(
        text.endswith("-hf-publication-receipt/v1")
        and "hf-publication-receipt" in text
    )


__all__ = [
    "ABBY_VOICE_CANONICAL_RELEASE_SCHEMA",
    "ABBY_VOICE_COMMIT_MESSAGE",
    "ABBY_VOICE_DEFAULT_REPOSITORY_ID",
    "ABBY_VOICE_GOAL_ID",
    "ABBY_VOICE_PLAN_SCHEMA",
    "ABBY_VOICE_POINTER_PATH",
    "ABBY_VOICE_PROFILE_ID",
    "ABBY_VOICE_PROGRAM_ID",
    "ABBY_VOICE_RECEIPT_SCHEMA",
    "ABBY_VOICE_RELEASE_PREFIX_TEMPLATE",
    "BASE_PROHIBITED_OPERATIONS",
    "DEFAULT_REPOSITORY_TYPE",
    "DEFAULT_TARGET_REVISION",
    "HuggingFacePublicationProfile",
    "PATENT_LEGAL_CANONICAL_RELEASE_SCHEMA",
    "PATENT_LEGAL_COMMIT_MESSAGE",
    "PATENT_LEGAL_DEFAULT_REPOSITORY_ID",
    "PATENT_LEGAL_GOAL_ID",
    "PATENT_LEGAL_PLAN_SCHEMA",
    "PATENT_LEGAL_POINTER_PATH",
    "PATENT_LEGAL_PROFILE_ID",
    "PATENT_LEGAL_PROGRAM_ID",
    "PATENT_LEGAL_RECEIPT_SCHEMA",
    "PATENT_LEGAL_RELEASE_PREFIX_TEMPLATE",
    "PublicationProfileError",
    "abby_voice_publication_profile",
    "get_publication_profile",
    "is_known_plan_schema",
    "is_known_receipt_schema",
    "patent_legal_publication_profile",
]
