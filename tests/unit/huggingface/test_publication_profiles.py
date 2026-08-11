"""Unit tests for parameterized Hugging Face publication profiles (PATLAW-100)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.huggingface.publication_profile import (
    ABBY_VOICE_GOAL_ID,
    ABBY_VOICE_PLAN_SCHEMA,
    ABBY_VOICE_RECEIPT_SCHEMA,
    BASE_PROHIBITED_OPERATIONS,
    PATENT_LEGAL_GOAL_ID,
    PATENT_LEGAL_PLAN_SCHEMA,
    PATENT_LEGAL_RECEIPT_SCHEMA,
    HuggingFacePublicationProfile,
    PublicationProfileError,
    abby_voice_publication_profile,
    get_publication_profile,
    patent_legal_publication_profile,
)
from ipfs_datasets_py.huggingface.publisher import (
    HUGGINGFACE_PUBLICATION_PLAN_SCHEMA,
    HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA,
)


_ABBY_MARKERS = (
    "abby-voice",
    "abby_voice",
    "abby-tts",
    "ABBY-VOICE",
)


def test_base_prohibited_operations_cover_destructive_labels() -> None:
    required = {
        "delete",
        "deletefile",
        "deletefolder",
        "move",
        "copy",
        "overwrite_legacy",
        "force_push",
        "rewrite_main",
    }
    assert required.issubset(BASE_PROHIBITED_OPERATIONS)


def test_abby_voice_profile_preserves_legacy_wire_identities() -> None:
    profile = abby_voice_publication_profile()
    assert profile.profile_id == "abby-voice"
    assert profile.goal_id == ABBY_VOICE_GOAL_ID
    assert profile.plan_schema_version == ABBY_VOICE_PLAN_SCHEMA
    assert profile.receipt_schema_version == ABBY_VOICE_RECEIPT_SCHEMA
    assert profile.plan_schema_version == HUGGINGFACE_PUBLICATION_PLAN_SCHEMA
    assert profile.receipt_schema_version == HUGGINGFACE_PUBLICATION_RECEIPT_SCHEMA
    assert profile.repository_id == "Publicus/211-abby-tts"
    assert profile.release_prefix_template == "data/abby_voice_v2/{release_id}"
    assert profile.pointer_path == "runtime/abby_voice_release_pointer.json"
    assert profile.require_pinned_verification_before_promotion is True
    assert profile.allow_remote_write_on_dry_run is False
    assert BASE_PROHIBITED_OPERATIONS.issubset(profile.prohibited_operations)


def test_patent_legal_profile_has_no_unrelated_program_schema_strings() -> None:
    profile = patent_legal_publication_profile()
    assert profile.profile_id == "patent-legal"
    assert profile.goal_id == PATENT_LEGAL_GOAL_ID
    assert profile.plan_schema_version == PATENT_LEGAL_PLAN_SCHEMA
    assert profile.receipt_schema_version == PATENT_LEGAL_RECEIPT_SCHEMA
    assert profile.plan_schema_version != ABBY_VOICE_PLAN_SCHEMA
    assert profile.receipt_schema_version != ABBY_VOICE_RECEIPT_SCHEMA

    payload = json.dumps(profile.to_dict(), sort_keys=True)
    for marker in _ABBY_MARKERS:
        assert marker.casefold() not in payload.casefold(), marker

    # Explicit field walk — to_dict must not smuggle Abby schemas.
    for key, value in profile.to_dict().items():
        if isinstance(value, str):
            lowered = value.casefold()
            for marker in _ABBY_MARKERS:
                assert marker.casefold() not in lowered, (key, value, marker)


def test_patent_legal_profile_repository_is_configurable() -> None:
    profile = patent_legal_publication_profile(
        repository_id="JusticeDAO/ipfs_uscode"
    )
    assert profile.repository_id == "JusticeDAO/ipfs_uscode"
    assert profile.with_repository("JusticeDAO/other").repository_id == (
        "JusticeDAO/other"
    )


def test_profile_refuses_to_weaken_prohibited_operations() -> None:
    with pytest.raises(PublicationProfileError, match="weakens prohibited"):
        HuggingFacePublicationProfile(
            profile_id="patent-legal",
            program_id="patent-legal-intelligence",
            goal_id=PATENT_LEGAL_GOAL_ID,
            plan_schema_version=PATENT_LEGAL_PLAN_SCHEMA,
            receipt_schema_version=PATENT_LEGAL_RECEIPT_SCHEMA,
            repository_id="JusticeDAO/patent-legal-public",
            release_prefix_template="data/patent_legal/{release_id}",
            pointer_path="runtime/patent_legal_release_pointer.json",
            prohibited_operations=frozenset({"delete"}),  # missing base set
        )


def test_profile_refuses_dry_run_write_or_unverified_promotion() -> None:
    with pytest.raises(PublicationProfileError, match="dry run"):
        HuggingFacePublicationProfile(
            profile_id="patent-legal",
            program_id="patent-legal-intelligence",
            goal_id=PATENT_LEGAL_GOAL_ID,
            plan_schema_version=PATENT_LEGAL_PLAN_SCHEMA,
            receipt_schema_version=PATENT_LEGAL_RECEIPT_SCHEMA,
            repository_id="JusticeDAO/patent-legal-public",
            release_prefix_template="data/patent_legal/{release_id}",
            pointer_path="runtime/patent_legal_release_pointer.json",
            allow_remote_write_on_dry_run=True,
        )
    with pytest.raises(PublicationProfileError, match="pinned verification"):
        HuggingFacePublicationProfile(
            profile_id="patent-legal",
            program_id="patent-legal-intelligence",
            goal_id=PATENT_LEGAL_GOAL_ID,
            plan_schema_version=PATENT_LEGAL_PLAN_SCHEMA,
            receipt_schema_version=PATENT_LEGAL_RECEIPT_SCHEMA,
            repository_id="JusticeDAO/patent-legal-public",
            release_prefix_template="data/patent_legal/{release_id}",
            pointer_path="runtime/patent_legal_release_pointer.json",
            require_pinned_verification_before_promotion=False,
        )


def test_patent_legal_profile_rejects_abby_schema_injection() -> None:
    with pytest.raises(PublicationProfileError, match="unrelated program"):
        HuggingFacePublicationProfile(
            profile_id="patent-legal",
            program_id="patent-legal-intelligence",
            goal_id=PATENT_LEGAL_GOAL_ID,
            plan_schema_version=ABBY_VOICE_PLAN_SCHEMA,
            receipt_schema_version=PATENT_LEGAL_RECEIPT_SCHEMA,
            repository_id="JusticeDAO/patent-legal-public",
            release_prefix_template="data/patent_legal/{release_id}",
            pointer_path="runtime/patent_legal_release_pointer.json",
        )


def test_get_publication_profile_aliases() -> None:
    assert get_publication_profile("abby-voice").goal_id == ABBY_VOICE_GOAL_ID
    assert get_publication_profile("patent-legal").goal_id == PATENT_LEGAL_GOAL_ID
    assert get_publication_profile("justicedao").profile_id == "patent-legal"
    with pytest.raises(PublicationProfileError, match="unknown"):
        get_publication_profile("unknown-program")


def test_release_prefix_for_formats_release_id() -> None:
    profile = patent_legal_publication_profile()
    assert (
        profile.release_prefix_for("release-v1")
        == "data/patent_legal/release-v1"
    )
    with pytest.raises(PublicationProfileError, match="unsafe release_id"):
        profile.release_prefix_for("../escape")
